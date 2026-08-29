# Control Tower

Plataforma de inteligencia operativa para pagos que detecta anomalías de
conversión, valida su persistencia, diagnostica la causa raíz, estima el impacto
financiero y propone acciones sujetas a revisión humana.

La demo monitorea tráfico sintético de México, Colombia y Brasil, con tres
merchants, tres proveedores, métodos de pago locales y bancos emisores.

## Capacidades

- Histórico sintético de 60 días y 500,000 transacciones.
- Tráfico live multisegmento con incidentes controlados.
- Baselines equivalentes a cada nivel de detección.
- Ventanas adaptativas de uno y cinco minutos.
- Detección estadística con corrección FDR y persistencia temporal.
- Consolidación de síntomas en causas raíz de provider o issuing bank.
- Impacto financiero normalizado a USD.
- Priorización P1–P4 con guardrails operativos explicables.
- Recomendaciones por área y flujo de aprobación humana con auditoría.
- API FastAPI y dashboard HTML conectado al backend.

## Estructura

```text
Control-Tower/
├── src/                     # Simulación, detección, diagnóstico y API
├── data/                    # CSV y JSON sintéticos usados por la demo
├── docs/                    # Contratos de datos de la UI
├── PRSM_Prototype/
│   ├── html/                # Dashboard HTML/CSS/JavaScript
│   └── streamlit/           # Prototipo alternativo en Streamlit
├── requirements.txt
└── Procfile
```

## Instalación

Requiere Python 3.12 o compatible.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install numpy scipy
```

## API

Inicia el backend desde la raíz:

```bash
uvicorn src.api:app --reload --port 8000
```

Rutas disponibles:

- `GET /`
- `GET /health`
- `GET /incidents`
- `GET /incidents/{incident_id}`
- `GET /audit-log`
- `POST /incidents/{incident_id}/review`

La documentación interactiva local queda en
`http://127.0.0.1:8000/docs`.

En producción se utiliza el comando del `Procfile`, sin `--reload`:

```bash
uvicorn src.api:app --host 0.0.0.0 --port $PORT
```

## Dashboard HTML

El dashboard está en `PRSM_Prototype/html/` y consume la API configurada en
`API_URL`, dentro de `app.js`. Si la API no está disponible, carga el escenario
demo como fallback.

No abras `index.html` directamente. Levanta un servidor estático:

```bash
cd PRSM_Prototype/html
python -m http.server 5500
```

Después abre `http://localhost:5500`.

## Flujo analítico

La explicación completa de arquitectura, estadística, falsos positivos y lógica
de cada módulo está en [docs/TECHNICAL_GUIDE.md](docs/TECHNICAL_GUIDE.md).

```text
transactions_live_multisegment.csv
  → detection_aggregator.py
  → adaptive_windows.py
  → anomaly_scanner.py
  → anomaly_validator.py
  → incident_clusterer.py
  → root_cause_engine.py
  → incident_consolidator.py
  → financial_impact.py
  → priority_engine.py
  → recommendation_engine.py
  → human_review.py
  → api.py
```

Los artefactos intermedios se guardan en `data/` para que cada etapa sea
inspeccionable y reproducible durante la demo.

## Datos y supuestos

Todos los datos son sintéticos. Los importes, configuraciones financieras,
probabilidades de recuperación y latencias no representan desempeño real de
merchants, bancos o proveedores.

Las tasas de cambio son constantes para la simulación:

| Moneda | USD por unidad |
|---|---:|
| MXN | 0.055 |
| COP | 0.00025 |
| BRL | 0.20 |
| USD | 1.00 |

No deben interpretarse como tasas de mercado actuales.

## Principio del producto

El sistema no solo indica que bajó la conversión. Busca explicar qué falló,
mostrar la evidencia, cuantificar el costo y recomendar la siguiente acción sin
ejecutarla automáticamente. Las decisiones operativas permanecen bajo control
humano y quedan registradas en el audit log.
