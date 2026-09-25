# Quant Agent Ensemble: RFQ Agents

Repositorio del Trabajo Fin de Máster **«Generación automatizada de peticiones de pricing (RFQs) para productos derivados empleando LLM»**, de Miguel Prieto Lezana, Máster Universitario en Tecnologías del Sector Financiero: FinTech de la Universidad Carlos III de Madrid.

El proyecto implementa y evalúa una arquitectura híbrida que transforma peticiones en lenguaje natural de *Interest Rate Swaps* en una RFQ estructurada mediante Protocol Buffers. Los agentes clasifican e interpretan la petición; Python valida la coherencia financiera y genera la salida final de forma determinista.

## Resultado principal

- 23 casos de referencia en cinco familias.
- 6 modelos comparados de OpenAI y Anthropic.
- 84 pruebas automatizadas.
- `gpt-5.6-terra`: 23/23 y USD 0.0102 por caso correcto.
- 8 defectos de instrumentación documentados y auditados.

## Contenido

- [`rfq-agents/`](rfq-agents/): código, configuración, pruebas y documentación completa.
- [`rfq-agents/README.md`](rfq-agents/README.md): instalación, arquitectura, ejecución y resultados.
- [`rfq-agents/evaluation/results/`](rfq-agents/evaluation/results/): bases SQLite archivadas que sustentan la evaluación.
- [`rfq-agents/docs/Overleaf/`](rfq-agents/docs/Overleaf/): fuentes LaTeX de los capítulos y bibliografía.

## Verificación local sin llamadas a modelos

```powershell
cd rfq-agents
python -m pytest -q
python tools/check_cases.py
```

Estas comprobaciones validan las 84 pruebas y la coherencia de los 23 casos sin realizar llamadas a OpenAI ni Anthropic.

Consulta la [documentación técnica completa](rfq-agents/README.md) para reproducir el entorno y revisar la evidencia experimental.