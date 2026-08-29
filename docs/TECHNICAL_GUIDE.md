# Guía técnica completa de Control Tower

Este documento explica qué hace el sistema, cómo fluye la información, qué
responsabilidad tiene cada archivo y cómo se controlan el ruido estadístico y los
falsos positivos.

## 1. Objetivo

Control Tower convierte intentos de pago en incidentes operables. Su trabajo no
termina al detectar una caída de conversión: también intenta determinar la causa,
cuantificar la exposición económica, asignar prioridad, recomendar acciones y
mantener a una persona como responsable de la decisión final.

La demo representa una red LATAM con:

- Países: MX, CO y BR.
- Merchants: Merchant_A, Merchant_B y Merchant_C.
- Providers: Stripe, Adyen y dLocal.
- Métodos: card, wallet, cash_in_store, PSE y PIX.
- Bancos emisores específicos por país.

Los datos, tasas, incidentes e importes son sintéticos.

## 2. Arquitectura de extremo a extremo

```text
Histórico de 60 días                  Tráfico live multisegmento
transactions_history_60_days.csv      transactions_live_multisegment.csv
              |                                      |
              v                                      v
baselines históricos                  agregación por minuto y dimensión
              |                                      |
              +------------ comparación ------------+
                                     |
                                     v
                         candidatos de anomalía
                                     |
                          FDR + persistencia
                                     |
                                     v
                          ventanas validadas
                                     |
                    clustering temporal por segmento
                                     |
                     diagnóstico y consolidación
                                     |
          impacto financiero -> prioridad -> recomendaciones
                                     |
                        revisión humana + auditoría
                                     |
                              FastAPI -> UI
```

## 3. Datos de entrada y contratos

### Transacciones históricas

`data/transactions_history_60_days.csv` contiene 500,000 intentos distribuidos
en 60 días. Incluye dimensiones de pago, estado, código de rechazo, importe,
moneda, reintentos, recuperación y latencia.

Para construir baselines se usan solo intentos originales. Mezclar reintentos
reduciría artificialmente la conversión esperada: en la simulación, los intentos
originales convierten cerca de 90%, mientras que los retries recuperan una
fracción mucho menor.

### Transacciones live

`data/transactions_live_multisegment.csv` contiene 12 minutos y 1,200 intentos
por minuto. Cada registro conserva `injected_incident_id`; esta columna es
ground truth de laboratorio y no existiría en producción.

Los incidentes inyectados son:

- INC-001: degradación de Adyen en Brasil con `PROCESSOR_ERROR`.
- INC-002: indisponibilidad de BBVA para Merchant_A en México con
  `ISSUER_UNAVAILABLE`.

### Configuración financiera

- `merchant_financial_config.csv`: fees, margen, recuperación de retries,
  prioridad del merchant y volumen mensual.
- `exchange_rates.csv`: tasas constantes a USD para la demo.

## 4. Simulación

### `src/simulator.py`

Genera el histórico. Modela distribución horaria, país, método, provider,
banco, conversión, importe, moneda, retries y latencia. Valida que:

- un pago aprobado no tenga `decline_code`;
- un pago rechazado sí tenga código;
- cada retry apunte a una transacción existente;
- `amount_usd` coincida con la tasa configurada.

### `src/validate_history.py`

Audita fechas, nulos, volumen diario y horario, estados y conversión por país,
provider, método y combinación de dimensiones. Sirve para impedir que el
detector aprenda un histórico que ya nace degradado.

### `src/incident_injector.py`

Define `IncidentRule`. Una regla tiene ventana temporal, tasa degradada, código
de rechazo y filtros opcionales. Una transacción puede coincidir con varias
reglas; el simulador selecciona la de menor tasa de aprobación.

### `src/live_simulator.py`

Genera tráfico live reproducible usando semillas de `random` y NumPy. Añade
importe y moneda, aplica reglas de incidente y guarda el ground truth. La tasa
normal depende del país, provider y método.

## 5. Baselines

Un baseline es la conversión esperada para un segmento comparable. Comparar un
segmento live granular contra una media global puede crear una anomalía falsa.

### `src/baseline.py`

Construye el baseline segmentado original a partir de intentos no retry y añade
`weekday` y `hour`.

### `src/hierarchical_baseline.py`

Construye distintos niveles de respaldo. Si no existe evidencia suficiente para
la combinación más detallada, permite retroceder hacia una referencia más amplia.

### `src/baseline_selector.py`

Selecciona el primer baseline confiable de la jerarquía. El mínimo actual es 30
intentos históricos. Devuelve tasa esperada, ticket promedio, muestra histórica,
nivel utilizado y dimensiones efectivas.

### `src/detection_level_baselines.py`

Crea baselines que corresponden exactamente a cada nivel live:

| Nivel | Dimensiones principales |
|---|---|
| L1 | provider + country |
| L2 | method + country |
| L3 | merchant + country |
| L4 | bank + country |
| L5 | provider + method + country |
| L6 | merchant + bank + country |

Todos agregan `weekday` y `hour`. El scanner intenta primero esta coincidencia
exacta y usa el selector jerárquico solo como fallback.

Un baseline exacto no siempre es mejor: con muestras pequeñas su tasa es muy
variable. En la demo, los baselines L6 con alrededor de 47 intentos históricos
incrementaron el ruido. Esa observación motivó el control posterior por FDR y
persistencia, en lugar de mover umbrales arbitrariamente.

## 6. Agregación live y ventanas adaptativas

### `src/detection_aggregator.py`

Agrupa el live por minuto para los seis niveles. Calcula intentos, aprobaciones,
rechazos, conversión, código dominante y ground truth.

No guarda solamente un incidente dominante. También conserva:

- `injected_records`: registros inyectados dentro de la ventana;
- `injected_share`: `injected_records / attempts`;
- `incident_ids`: todos los IDs presentes, separados por `|`.

Esto permite distinguir evidencia directa, contaminación parcial y ventanas
completamente limpias.

### `src/adaptive_windows.py`

Usa una ventana rápida de un minuto cuando hay al menos 30 intentos. Si no, suma
una ventana móvil de cinco minutos. Si ni así alcanza el mínimo, marca
`insufficient_data`.

Las ventanas de cinco minutos suman intentos, aprobaciones, rechazos y registros
inyectados; también recalculan `injected_share` y unen todos los `incident_ids`.

### `src/multisegment_aggregator.py`

Es un agregador previo y más simple que genera `live_segment_windows.csv`. Sigue
siendo útil para el payload agregado del dashboard, mientras que
`detection_aggregator.py` alimenta el pipeline estadístico multinivel.

## 7. Estadística de detección

### `src/anomaly_detector.py`

Para una ventana con tasa observada `p_obs`, baseline `p_exp` y `n` intentos,
calcula:

```text
error_estándar = sqrt(p_exp * (1 - p_exp) / n)
z = (p_exp - p_obs) / error_estándar
caída = p_exp - p_obs
```

Es una prueba unilateral: solo interesa una caída de conversión. Una ventana es
candidata confirmada cuando cumple simultáneamente:

- `n >= 30`;
- caída de al menos 5 puntos porcentuales;
- `z >= 2`.

Estados posibles:

- `normal`: variación aceptable;
- `potential_anomaly`: hay caída, pero falta evidencia estadística;
- `confirmed_anomaly`: supera los tres filtros;
- `insufficient_data`: volumen live insuficiente.

La severidad solo se asigna a `confirmed_anomaly`.

### `src/anomaly_scanner.py`

Recorre todas las ventanas, busca el baseline exacto del mismo nivel y llama al
detector. Si el exacto no es confiable, usa el baseline jerárquico. Produce
`anomaly_candidates.csv` con baseline elegido, caída, z-score, severidad y razón.

Clasifica las ventanas confirmadas por ground truth:

- directa: `injected_share >= 0.50`;
- parcial: entre 1% y 49.9999%;
- limpia: `injected_share == 0`.

Las ventanas limpias son candidatos a falsos positivos, no prueba definitiva de
que el algoritmo esté equivocado.

## 8. Control de falsos positivos

El scanner realiza cientos de comparaciones simultáneas. Incluso con un umbral
razonable, algunas pueden resultar significativas por azar.

### `src/anomaly_validator.py`

Aplica dos barreras adicionales.

#### 8.1 Benjamini–Hochberg

Convierte cada z-score en un p-value unilateral:

```text
p_value = P(Z >= z_score)
```

Dentro de cada minuto ordena los `m` tests por p-value y calcula:

```text
umbral_BH(i) = (i / m) * 0.05
```

Acepta hasta el mayor rango que cumple `p(i) <= umbral_BH(i)`. Esto controla la
tasa esperada de falsos descubrimientos (FDR), que no es lo mismo que garantizar
que 5% de cada resultado sea falso.

#### 8.2 Persistencia

Crea una clave con nivel y dimensiones. Una anomalía debe superar FDR durante
al menos dos minutos consecutivos para recibir `validated_anomaly = True`. Una
señal aislada se considera ruido transitorio.

En una ejecución de referencia:

```text
217 ventanas confirmadas inicialmente
171 ventanas después de FDR
111 ventanas después de FDR + persistencia
23 ventanas validadas con injected_share = 0
```

Antes de estas barreras existían 66 ventanas limpias confirmadas. La reducción
a 23 muestra que el control elimina ruido sin perder INC-001 ni INC-002.

### `src/persistent_detector.py`

Implementa la máquina de estados conceptual para un solo segmento:

```text
normal -> investigating -> confirmed -> recovering -> normal
```

El validador extiende esta idea a todos los segmentos del dataframe.

## 9. De ventanas a incidentes

### `src/incident_clusterer.py`

Agrupa ventanas validadas por nivel y dimensiones visibles. Separa clusters
temporales cuando el hueco supera dos minutos. Resume duración, intentos, tasas,
z-score, código dominante y ground truth.

### `src/root_cause_engine.py`

Infere el tipo de causa por el nivel que aportó la evidencia:

- niveles de provider -> `provider`;
- niveles bancarios -> `issuing_bank`;
- nivel merchant -> `merchant`;
- nivel method -> `payment_method`.

Fusiona candidatos compatibles por dimensión, país y superposición temporal.

### `src/incident_consolidator.py`

Evita presentar cada síntoma como incidente independiente. Calcula confianza a
partir de tipo de causa, ventanas, candidatos, caída, z-score y naturaleza del
código de rechazo.

Ordena candidatos y elige secuencialmente causas primarias fuertes. Providers y
bancos necesitan confianza de al menos 0.70. Después realiza una segunda pasada
para absorber síntomas con mismo país, tiempo y código técnico.

Ejemplos:

- Itaú, Bradesco, PIX y wallet con `PROCESSOR_ERROR` son síntomas del incidente
  Adyen + BR.
- Señales por provider con `ISSUER_UNAVAILABLE` pueden ser síntomas de BBVA +
  Merchant_A + MX, porque un fallo del emisor cruza varios providers.

Los candidatos débiles o con códigos normales permanecen en
`unresolved_incident_candidates.csv`; el sistema no inventa una causa.

## 10. Impacto financiero y prioridad

### `src/financial_impact.py`

Filtra las transacciones que coinciden con dimensiones y tiempo del incidente.
Luego estima:

```text
aprobaciones_esperadas = intentos * tasa_esperada
aprobaciones_perdidas = max(esperadas - reales, 0)
GPV_en_riesgo = aprobaciones_perdidas * ticket_promedio_USD
valor_recuperable = GPV_en_riesgo * retry_recovery_rate
valor_neto = GPV_en_riesgo - valor_recuperable
revenue_en_riesgo = valor_neto * platform_fee_rate
valor_por_minuto = valor_neto / duración
```

Esto es una estimación contrafactual, no contabilidad definitiva.

### `src/priority_engine.py`

El score compuesto pondera impacto financiero, confianza, duración, alcance de
merchants, alcance de la causa y criticidad del merchant.

Además usa guardrails operativos. Una falla técnica confirmada no puede quedar
subpriorizada solo porque el valor por minuto sea menor a USD 1,000:

- P1 para falla técnica extensa o impacto crítico con confianza >= 90%;
- P2 mínimo para falla técnica material con confianza >= 80% y suficiente
  impacto o aprobaciones perdidas;
- en los demás casos aplica los cortes del score: 80, 60 y 40.

Cada fila conserva `priority_reason` para explicar la decisión.

## 11. Recomendaciones y control humano

### `src/recommendation_engine.py`

Genera título, acción principal y recomendaciones para Payments Operations,
Engineering, Finance, Merchant Success y liderazgo. La recomendación depende de
causa, prioridad, confianza e impacto; no ejecuta acciones externas.

### `src/human_review.py`

Gestiona transiciones:

```text
proposed -> approved | rejected | modified
modified -> approved | rejected | modified
approved -> executed | rejected | modified
```

Registra reviewer, comentario, timestamps, cambios a la acción y audit log.
`rejected` y `executed` son estados terminales.

## 12. API y dashboard

### `src/api.py`

Expone salud, dashboard, incidentes, detalle, análisis asistido, auditoría,
revisión y notificación de prueba. Enriquece incidentes con taxonomía, playbook y
matriz de prioridad cuando esas tablas existen.

Puede usar Anthropic para generar una explicación narrativa basada solo en el
JSON del incidente. Esta capa no sustituye el detector ni decide la prioridad.
Requiere credenciales en variables de entorno. También puede publicar avisos en
ntfy cuando `NTFY_TOPIC` está configurado.

La revisión escrita por la API persiste en `reviewed_incidents.csv` y
`recommendation_audit_log.csv`.

### `PRSM_Prototype/html/app.js`

Carga `/incidents` desde la API pública, transforma el contrato del backend al
modelo visual y construye un escenario live ponderado por intentos. Si la API
falla, usa los escenarios determinísticos de demo.

### `PRSM_Prototype/streamlit/`

Contiene una versión alternativa del prototipo. Usa datos incluidos dentro de su
propia carpeta y no es el frontend principal conectado a FastAPI.

## 13. Orden de ejecución

Para reconstruir la demo desde el live existente:

```bash
python src/detection_aggregator.py
python src/adaptive_windows.py
python src/anomaly_scanner.py
python src/anomaly_validator.py
python src/incident_clusterer.py
python src/root_cause_engine.py
python src/incident_consolidator.py
python src/financial_impact.py
python src/priority_engine.py
python src/recommendation_engine.py
python src/human_review.py
```

Para regenerar primero el live:

```bash
python src/live_simulator.py
```

Para reconstruir baselines históricos:

```bash
python src/baseline.py
python src/hierarchical_baseline.py
python src/detection_level_baselines.py
```

## 14. Límites de la demo

- Los datos y ground truth son sintéticos.
- Las tasas de cambio son fijas y no son datos de mercado.
- Los CSV actúan como persistencia; no hay transacciones ACID ni bloqueo para
  escrituras concurrentes.
- Los umbrales fueron calibrados para esta simulación y deben reevaluarse antes
  de producción.
- El z-test usa una aproximación normal binomial; segmentos pequeños requieren
  mayor cautela.
- FDR reduce falsos descubrimientos, pero no elimina todos los falsos positivos.
- Correlación temporal y dimensional no demuestra causalidad por sí sola.
- Las recomendaciones necesitan aprobación humana.
- El despliegue productivo debería sustituir CSV por almacenamiento duradero,
  autenticación, autorización, observabilidad y gestión segura de secretos.
