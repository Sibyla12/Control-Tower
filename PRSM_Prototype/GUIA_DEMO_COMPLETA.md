# Guía completa del dashboard — qué es cada cosa y para qué sirve

Este documento explica **cada botón, panel y pantalla** del dashboard de
Control Tower / PRISM, para que puedas explicarlo con confianza sin
depender de memoria. Todo lo que describe aquí es real — nada es
inventado ni simulado en el sentido de "falso": los datos vienen del
pipeline de detección real corriendo sobre tráfico simulado.

Para el guion cronometrado de 4 minutos (qué decir y cuándo), usa
[DEMO_GUIDE.md](DEMO_GUIDE.md). Este documento es la referencia de fondo:
qué es cada pieza y por qué existe.

---

## 1. Barra superior

| Elemento | Qué es | Para qué sirve |
|---|---|---|
| **Logo PRISM** | Marca del producto | — |
| **Señales (Signal caution / Critical signal)** | Dos contadores con forma de "corchete" arriba a la izquierda | Cuenta cuántos incidentes son de prioridad media (caution, ámbar) y cuántos son críticos (critical, rojo). Es un vistazo de un segundo al estado general antes de leer nada más. Solo aparece en modo Analyst. |
| **LIVE SIMULATION** | Etiqueta con punto verde animado | Deja claro que estás viendo tráfico simulado en vivo, no un mockup estático — el sistema está corriendo de verdad. |
| **Reloj** | Hora local del navegador | Referencia de tiempo real, no relacionada con los timestamps de los datos (que son de la simulación). |
| **Ícono de notificaciones** | Campana | Visual únicamente en el dashboard; las notificaciones reales llegan al teléfono vía ntfy.sh (push notifications), configuradas por separado en el backend. |
| **Toggle "Analyst view" / "Executive view"** | Botón que cambia el modo de la pantalla completa | Ver sección 4. Es el cambio más importante que puedes mostrar: mismo dato, dos audiencias distintas. |
| **Avatar "OP"** | Representa al usuario (Payment Operations) | Decorativo — identifica el rol de quien está usando el dashboard. |

---

## 2. Selector de tiempo (debajo de la barra superior)

Tres botones en línea:

- **"Live now"** — el estado actual, en vivo. Es el modo por default.
- **"Replay: before the incidents (10:00–10:02)"** — viaja el reloj hacia
  atrás y muestra exactamente cómo se veía el dashboard *antes* de que
  empezaran los incidentes (red saludable, 0 incidentes). No es una
  animación ni una versión inventada: usa el parámetro `?as_of=` de la API,
  que filtra los datos reales para solo mostrar lo que existía hasta ese
  minuto. Sirve para demostrar que el sistema no "siempre muestra
  incidentes" — el estado saludable es real y verificable.
- **"Trial by fire"** — abre el panel de inyección en vivo. Ver sección 8.

---

## 3. Vista Analyst (la vista completa, por default)

### 3.1 Status strip (la barra ancha justo debajo del selector de tiempo)

Muestra el estado general de la red en una frase: "SYSTEM HEALTHY" /
"Multiple live incidents detected and prioritized", con una descripción
corta debajo, y a la derecha cuándo se actualizó por última vez y la
ventana de baseline usada (6 horas).

### 3.2 KPIs principales (4 tarjetas)

| Tarjeta | Qué muestra |
|---|---|
| **Network conversion** | % de pagos aprobados sobre intentos, en toda la red, comparado contra lo esperado |
| **Active incidents** | Cuántos incidentes confirmados hay ahora mismo, y cuál es la prioridad más alta |
| **GMV at risk** | Dinero en riesgo por hora (USD), con una versión "ajustada por confianza" abajo |
| **Monitored traffic** | Cuántas transacciones se están vigilando y cuántos merchants/providers cubre |

### 3.3 Executive Summary (panel con 4 tarjetas + desglose)

Es el rollup financiero de **todos** los incidentes activos sumados:
impacto económico total, GMV en riesgo ajustado (vs. bruto sin ajustar),
ingreso de la plataforma en riesgo (comisiones), e impacto económico de
los merchants (margen perdido). Debajo, **"Where the current GMV at risk
concentrates"** — una serie de barras de chips que muestran, por
dimensión (causa raíz, país, provider, banco, decline code), qué
porcentaje del riesgo total representa cada valor. Es una señal
diagnóstica ("¿dónde se concentra el problema?"), explícitamente
etiquetada como *no* la causa raíz confirmada.

### 3.4 Geographic Operations (el mapa)

Un globo 3D orthográfico con México, Colombia y Brasil marcados. Cada país
cambia de color según su estado (verde = saludable, ámbar =
investigando, rojo = incidente), calculado contra **su propio baseline
histórico**, no un número absoluto — el pie del mapa lo aclara. Haz clic
en cualquier país para ver su detalle (o expandir/colapsar en la lista de
abajo del mapa).

### 3.5 Incident Priority (lista de incidentes)

Cada tarjeta es un incidente confirmado, ordenado por impacto económico:
prioridad (P1–P4) + severidad, hace cuánto empezó, título, subtítulo,
y tres métricas rápidas (caída de conversión, confianza del diagnóstico,
GMV en riesgo por hora). Haz clic en cualquiera para abrir el detalle
completo (sección 5).

### 3.6 Under Investigation

Anomalías que el sistema detectó estadísticamente pero que **no llegaron
al umbral de confianza de 0.70** necesario para declararlas como
incidente confirmado. En vez de forzar un diagnóstico con poca evidencia,
el sistema las deja aquí, explícitamente marcadas como "sin suficiente
evidencia todavía". Es una de las decisiones de diseño más importantes
del proyecto — preferimos ser honestos sobre la incertidumbre que
inventar una causa.

### 3.7 Live Performance (la gráfica)

Conversión real vs. esperada en los últimos 30 minutos, con una línea
punteada roja marcando el momento exacto en que se detectó el incidente.
Es el mismo tipo de gráfica que un ingeniero de guardia vería en un panel
de monitoreo real.

---

## 4. Vista Executive (el toggle "Executive view")

Pensada para alguien que necesita decidir rápido, no diagnosticar. Es un
**filtro visual puro** — no cambia ningún dato ni hace una petición
distinta a la API, solo oculta/muestra lo que ya está cargado.

| Bloque | Qué muestra |
|---|---|
| **Estado grande (NORMAL / WARNING / CRITICAL)** | La misma clasificación de estado que la barra de status, en formato grande y a color |
| **Active incidents** | Cuenta total + desglose "1 P1 · 2 P2" |
| **Financial exposure** | Los mismos $/hora del KPI "GMV at risk" |
| **Trend** | "Recovering" / "Worsening" / "Stable" — compara la conversión de ahora contra hace ~5 minutos, usando los mismos datos reales de la gráfica |
| **Chips de países** | Un vistazo rápido a qué país(es) están en problema, mismo estado que el mapa |
| **Una tarjeta por cada incidente P1** | País, % de confianza, el problema explicado en una frase (no jerga técnica), y la acción recomendada — con un botón **"Review & decide →"** que abre el detalle completo de ese incidente específico |
| **Gráfica de conversión** | La misma del modo Analyst, para respaldar visualmente el "Trend" |

Lo que se **oculta** en este modo: el desglose por causa/país/proveedor/
banco, el mapa geográfico, la lista completa de incidentes, el panel
"Under investigation", y dentro del detalle de cada incidente — causa
raíz técnica, evidencia, confianza de diagnóstico, desglose por segmento,
y proyecciones financieras a futuro.

---

## 5. Detalle de un incidente (el panel lateral / "drawer")

Se abre al hacer clic en cualquier incidente. Contiene, en orden:

1. **Título + resumen ejecutivo** — una frase en lenguaje simple con el
   impacto económico.
2. **Banner "Recognized pattern"** (si aplica) — aparece solo si este
   mismo tipo de falla (misma causa raíz, mismas dimensiones, mismo
   decline code) ya se vio antes en una corrida anterior del pipeline,
   con fecha/hora real de la primera y última vez que se vio. Esto es
   "memoria de incidentes" — el sistema reconoce patrones repetidos.
3. **AI Analysis** — botón "Generate analysis" que llama a GPT-4o con los
   datos estructurados del incidente y devuelve una narrativa en
   lenguaje natural. Sin `OPENAI_API_KEY` configurada, da un error 503
   explícito en vez de fallar en silencio.
4. **Root cause** *(solo modo Analyst)* — árbol/resumen de la causa raíz
   diagnosticada (provider, banco, merchant, método de pago o decline
   code).
5. **Evidence** *(solo modo Analyst)* — checklist de la evidencia
   estadística que sustenta el diagnóstico.
6. **Priority** — la prioridad asignada, cuánto dinero está en riesgo por
   hora, el % de confianza, y (si aplica) el ranking Pareto de este
   incidente frente a los demás activos.
7. **Operational Playbook** — quién es el dueño operativo, el nivel de
   escalación, y la **acción recomendada** — el texto que también se ve
   en la vista Executive.
8. **Observed vs Expected** *(solo modo Analyst)* — comparación directa
   de la tasa de aprobación observada contra la esperada.
9. **Economic Impact** — GMV en riesgo, cuánto es recuperable, cuántos
   intentos afectados, cuántas declinaciones de más (excess declines).
10. **Projections** *(solo modo Analyst)* — proyección de impacto a 4h,
    24h y 7 días, con una curva de recuperación asumiendo 6h de MTTR
    (tiempo medio de resolución).
11. **Diagnosis Confidence** *(solo modo Analyst)* — barra de confianza
    del diagnóstico y qué tan confiable es el baseline histórico contra
    el que se comparó.
12. **Segment Breakdown** *(solo modo Analyst)* — tabla Pareto de qué
    segmentos específicos (proveedor/banco/merchant/método) explican qué
    porcentaje de las declinaciones excedentes.
13. **Human Decision** — ver sección 6.

---

## 6. Human Decision (aprobar / modificar / rechazar / ejecutar)

Ningún incidente ejecuta su recomendación automáticamente. Un humano
tiene que decidir:

- **Approve** — aprueba la acción recomendada tal cual.
- **Modify** — abre un textarea para escribir una acción distinta antes
  de aprobar.
- **Reject** — rechaza la recomendación.
- **Execute** — solo disponible después de aprobar; marca la acción como
  ejecutada (con timestamp).

Pide tu nombre (mínimo 2 caracteres) y un comentario opcional. Cada
decisión queda registrada en `recommendation_audit_log.csv` — reviewer,
comentario, acción anterior, acción nueva, y timestamp — visible vía
`GET /audit-log`. Es la parte de "control humano" del sistema: PRISM
recomienda, pero nunca decide por su cuenta.

---

## 7. Ask PRISM (el botón flotante abajo a la derecha)

Un chat con IA (GPT-4o con function-calling) que responde preguntas sobre
el estado **actual y real** del sistema — nunca inventa datos porque
literalmente no tiene otra fuente: cada respuesta viene de llamar a las
mismas funciones que usan los endpoints normales de la API
(`/dashboard`, `/incidents`, `/incidents/{id}/segments`,
`/unresolved-candidates`). Ejemplos de preguntas que puedes hacer en vivo:

- "¿Cuántos incidentes P1 hay ahora mismo?"
- "¿Cuál es el incidente con mayor prioridad y qué segmento explica más
  las declinaciones excedentes?" (esta obliga al agente a encadenar dos
  herramientas — buena para mostrar que no es un chatbot con respuestas
  fijas)
- "¿Hay alguna anomalía que no se haya confirmado todavía?"

Si no responde o da 503, es porque la `OPENAI_API_KEY` no está
configurada en ese momento en el backend.

---

## 8. Trial by Fire (inyectar y detectar en vivo, sin terminal)

El feature pensado exactamente para el momento en que un juez pide "meto
una combinación que ustedes no ensayaron, a ver si la detectan de
verdad". Todo desde el navegador:

### Campos del formulario

| Campo | Qué hace |
|---|---|
| **Merchant / Provider / Country / Payment method / Issuing bank** | Cada uno es opcional. Si lo dejas en "Any", ese campo actúa como comodín (afecta a todos los valores de esa dimensión). Si el juez dice "un problema de Adyen en Brasil", pones Provider=Adyen, Country=BR, y dejas el resto en "Any". |
| **Decline code** | Obligatorio. Qué código de rechazo tendrán las transacciones degradadas (ej. `PROCESSOR_ERROR` para una falla técnica, `SUSPECTED_FRAUD` para un pico de fraude). |
| **Approval rate during incident** | Qué tan severa es la caída (0 a 1). Más bajo = incidente más severo = se detecta más rápido. |
| **Duration (minutes)** | Cuántos minutos de tráfico degradado se generan. El sistema necesita al menos 30 transacciones coincidentes para poder validar estadísticamente — combinaciones muy específicas con pocos minutos pueden no alcanzar ese mínimo. |

### Botones

- **Randomize** — llena el formulario con una combinación aleatoria y
  válida, para un demo de un clic.
- **Inject & run detection** — inyecta las transacciones reales al feed
  en vivo y corre el pipeline completo de 11 etapas (~10-15 segundos,
  barra de progreso real con las etapas por las que va pasando). Al
  terminar, dice honestamente uno de tres resultados:
  - **Confirmado como incidente** (cruzó el umbral de confianza 0.70)
  - **Marcado como candidato bajo investigación** (se detectó pero no
    alcanzó 0.70 — aparece en "Under Investigation")
  - **No detectado** (ni siquiera se validó estadísticamente — sugiere
    bajar más el approval rate o subir la duración)
- **Reset live feed to baseline** — botón ámbar debajo de "Inject & run
  detection" — deshace **todas** las inyecciones hechas hasta ese
  momento y vuelve el feed exactamente al estado original committeado,
  re-corriendo el pipeline. Pide confirmación antes de ejecutarse. Útil
  para dejar todo limpio antes de presentar, o entre pruebas.

**Nota técnica de seguridad:** si dos personas usan Trial by Fire (o
Reset) al mismo tiempo, el sistema rechaza la segunda petición
inmediatamente con un mensaje claro ("ya hay una corriendo, espera
10-15s") en vez de dejar que compitan por los mismos archivos — eso
evitaría que el sistema se corrompiera o se quedara colgado.

---

## 9. Preguntas que probablemente te hagan (y cómo responderlas)

**"¿Esto es data inventada?"**
No — es tráfico *simulado* (no viene de un procesador de pagos real
porque es un demo), pero cada número que ves en pantalla se calculó de
verdad a partir de ese tráfico simulado, corriendo el mismo pipeline
estadístico que correría sobre datos reales. Nada se hardcodea en el
frontend.

**"¿Qué pasa si el sistema se equivoca?"**
Por eso existe "Under Investigation" — el sistema prefiere decir "no sé
todavía" antes que inventar una causa con poca evidencia. Y por eso
existe Human Decision — nada se ejecuta sin que una persona lo apruebe.

**"¿Por qué confían en un umbral de 0.70?"**
Está documentado como una decisión explícita de trade-off en
[docs/DECISIONS.md](../docs/DECISIONS.md) — actionability vs. honestidad
diagnóstica.

**"¿Cómo sé que el Trial by Fire no está arreglado/hardcodeado?"**
Porque el "Reset" existe — puedes correrlo, ver que se detecta, resetear,
y volver a correrlo con otra combinación distinta las veces que quieras.
