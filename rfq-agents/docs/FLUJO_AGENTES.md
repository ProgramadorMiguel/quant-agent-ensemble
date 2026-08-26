# Flujo de la red de agentes

Descripción de qué hace cada agente, qué recibe y qué devuelve, con datos reales
de una ejecución registrada en `outputs/evaluations.db`.

**Dónde va cada parte en la memoria:**

| Sección de este documento | Sección de la memoria |
|---|---|
| 1. Visión general | 5.1 Arquitectura general |
| 2. Los tres agentes y la capa de validación | 5.5 Diseño de la red de agentes |
| 3. Ficha de cada agente | 6.4, 6.5 y 6.6 |
| 4. Traza completa con datos reales | 6.8 Ejemplo completo |
| 5. Coste y latencia por etapa | 9.5 Coste y latencia |

---

## 1. Visión general

El sistema convierte una petición escrita en lenguaje natural en un mensaje RFQ
protobuf válido. Lo hace en cuatro etapas: tres agentes LLM y una capa de
validación determinista intercalada entre el segundo y el tercero.

```
   petición en lenguaje natural
              │
              ▼
   ┌──────────────────────┐
   │ 1. Orquestador       │  LLM   ¿de qué producto hablamos?
   └──────────┬───────────┘
              │  "IRS"
              ▼
   ┌──────────────────────┐
   │ 2. Especialista      │  LLM   extraer los términos del trade
   └──────────┬───────────┘
              │  10 campos
              ▼
   ┌──────────────────────┐
   │ 3. Validación        │  Python  ¿están todos? ¿son coherentes?
   └──────────┬───────────┘
              │  campos validados          └─► si falta algo: se detiene aquí
              ▼
   ┌──────────────────────┐
   │ 4. Generador de RFQ  │  LLM   serializar al esquema pricing.proto
   └──────────┬───────────┘
              │
              ▼
        RFQ.textproto
```

El principio de diseño es que **el LLM solo interviene donde no hay alternativa
determinista**: comprender lenguaje. Validar y comprobar el esquema es código,
porque el código no alucina y se puede auditar.

---

## 2. Los tres agentes y la capa de validación

Cada agente se define en un fichero Markdown bajo `agents/`, y la red completa se
declara en `config/agents.yaml`. El prompt de sistema de un agente se compone
concatenando su fichero de instrucciones, su skill de producto (si lo tiene) y el
esquema `.proto` (si lo necesita).

Esta separación tiene una consecuencia práctica para el trabajo experimental:
**cambiar el comportamiento de un agente no requiere tocar código**, solo editar
un fichero de texto que queda versionado en git. Cada llamada registra además un
hash de sus instrucciones, de modo que cualquier resultado guardado puede
atribuirse a la versión exacta del prompt que lo produjo.

---

## 3. Ficha de cada agente

### 3.1 Agente orquestador

| | |
|---|---|
| Instrucciones | `agents/orchestrator_agent.md` |
| Entrada | Texto de la petición, tal cual lo escribió el usuario |
| Salida | Una etiqueta: `IRS` o `UNSUPPORTED` |
| Responsabilidad | Decidir si el sistema sabe tratar el producto descrito |
| No hace | Extraer campos, validar ni valorar |

Es la etapa más barata del sistema: consume del orden de 250 tokens de entrada y
devuelve **un solo token**. Su función real es de guarda: evita que una petición
sobre un producto no soportado avance por el resto del flujo y produzca una RFQ
sin sentido.

### 3.2 Agente especialista de producto

| | |
|---|---|
| Instrucciones | `agents/product_specialist_agent.md` |
| Skill | `skills/irs_extraction_skill.md` |
| Esquema | `protos/pricing.proto` |
| Entrada | El mismo texto original de la petición |
| Salida | Un mensaje `InterestRateSwap` en protobuf de texto |
| Responsabilidad | Traducir lenguaje humano a términos financieros estructurados |
| No hace | Validar, completar lo que falte ni valorar |

**Es el agente crítico del sistema.** Aquí ocurre la única tarea que un LLM hace
mejor que el código: interpretar que "pagamos fijo al 2,75% contra EURIBOR a seis
meses" significa `direction: PAYER_FIXED`, `fixed_rate: 0.0275`,
`floating_index: "EURIBOR"`, `floating_tenor: "6M"`.

El skill le prohíbe explícitamente inferir valores no declarados. Si la petición
no menciona la curva de descuento, debe omitir el campo, no deducirlo de la
convención de mercado. Esa prohibición es lo que hace medible la alucinación.

### 3.3 Capa de validación (no es un agente)

| | |
|---|---|
| Implementación | `src/validation/irs_validator.py` |
| Entrada | Los campos extraídos |
| Salida | Válido o inválido, con la lista de campos ausentes y errores |
| Coste | Cero tokens, tiempo despreciable |

Comprueba que estén los diez términos obligatorios y que sean coherentes: nocional
positivo, dirección dentro del enumerado, fecha de inicio anterior al vencimiento.

Es determinista por decisión de diseño: es la garantía de que ninguna RFQ mal
formada llega a la etapa de valoración, independientemente de lo que haga el
modelo. Una petición que no supera esta capa **se detiene aquí** y no genera RFQ.

### 3.4 Agente generador de RFQ

| | |
|---|---|
| Instrucciones | `agents/rfq_proto_agent.md` |
| Esquema | `protos/pricing.proto` |
| Entrada | Los campos ya validados, más el identificador de la petición |
| Salida | El mensaje `RFQ` completo en protobuf de texto |
| Responsabilidad | Serializar al esquema, copiando valores sin transformarlos |

Este agente tiene un estatus particular en el trabajo. Su salida se compara
siempre contra la de un mapeador determinista (`fields_to_textproto`), que es la
que el sistema utiliza realmente. El agente se conserva como **sujeto de medida**:
la tasa de coincidencia entre ambos responde a una pregunta legítima — ¿es capaz
un LLM de serializar correctamente contra un esquema que se le proporciona, o
conviene dejar siempre el ensamblaje al código?

Los datos de la sección 5 sugieren la respuesta.

---

## 4. Traza completa con datos reales

Ejecución `69cdc288ed08…`, modelo `gpt-4.1-mini`, extraída de la telemetría.

**Petición original**

```
Generate an RFQ for a vanilla EUR interest rate swap with notional EUR 10,000,000.
We pay fixed at 2.75% and receive 6M EURIBOR. The effective date is 2026-09-01
and the maturity date is 2031-09-01. Use EUR-OIS as the discount curve and
EUR-EURIBOR-6M as the forwarding curve.
```

**Etapa 1 — Orquestador** · 700 ms · 248 tokens entrada / 1 salida

```
IRS
```

**Etapa 2 — Especialista** · 4.155 ms · 649 tokens entrada / 90 salida

```
notional: 10000000
currency: "EUR"
direction: PAYER_FIXED
effective_date: "2026-09-01"
maturity_date: "2031-09-01"
fixed_rate: 0.0275
floating_index: "EURIBOR"
floating_tenor: "6M"
discount_curve: "EUR-OIS"
forwarding_curve: "EUR-EURIBOR-6M"
```

Obsérvese la conversión de `2.75%` a `0.0275` y la deducción de `PAYER_FIXED` a
partir de "we pay fixed".

**Etapa 3 — Validación** · 0 ms · 0 tokens

```
status: VALID
missing_fields: none
errors: none
```

**Etapa 4 — Generador de RFQ** · 2.147 ms · 392 tokens entrada / 125 salida

```
rfq_id: "69cdc288ed084339b9d0b6368731511b"
irs {
  notional: 10000000.0
  currency: "EUR"
  direction: PAYER_FIXED
  effective_date: "2026-09-01"
  maturity_date: "2031-09-01"
  fixed_rate: 0.0275
  floating_index: "EURIBOR"
  floating_tenor: "6M"
  discount_curve: "EUR-OIS"
  forwarding_curve: "EUR-EURIBOR-6M"
}
```

**Total: 7,0 segundos y 1.505 tokens.**

---

## 5. Coste y latencia por etapa

Medias sobre 49 llamadas registradas con `gpt-4.1-mini`:

| Agente | Llamadas | ms medios | Tokens entrada | Tokens salida | Coste |
|---|---|---|---|---|---|
| Orquestador | 17 | 1.545 | 4.078 | 17 | $0,0008 |
| Especialista | 17 | 1.989 | 10.895 | 1.438 | $0,0031 |
| Generador de RFQ | 15 | 2.190 | 5.906 | 1.903 | $0,0025 |

Dos lecturas relevantes para el capítulo de resultados:

**El orquestador es prácticamente gratis** (13% del coste, 17 tokens de salida en
17 llamadas). Su presencia no penaliza el sistema.

**El generador de RFQ cuesta el 39% del total** y su salida es, campo por campo,
la misma información que recibe: solo añade comillas, llaves y el identificador.
Es un formateo que el mapeador determinista realiza en microsegundos y sin coste.
Cuantificar esa diferencia es precisamente el objeto de la métrica de fidelidad
de serialización.

---

## 6. Qué falta en el flujo actual

Estado a fecha de este documento, para no confundir lo implementado con lo
planificado:

- Un único producto (IRS). La ficha de la sección 3.2 se replicará por producto
  en cuanto exista el registro multiproducto.
- Un único proveedor (OpenAI). La abstracción de proveedores es la sección 5.9 de
  la memoria.
- Una única topología (tres agentes). La variante monolítica de una sola llamada,
  con la que se compara, es la sección 5.6.
- Sin valoración: el flujo termina en la RFQ. La etapa de QuantLib es el capítulo 7.
