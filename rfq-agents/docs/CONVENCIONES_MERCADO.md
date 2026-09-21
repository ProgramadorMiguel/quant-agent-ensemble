# Convenciones de mercado

Verificado el **21/09/2026** contra fuente primaria. Alcance del trabajo: **EUR y
USD**. GBP queda descartado.

Este documento es la fuente de verdad de las convenciones que el sistema deriva
cuando la petición no las enuncia. Todo valor aquí recogido está contrastado; lo
que no lo esté se marca explícitamente.

---

## Fuentes

| Fuente | Qué aporta | Clave de cita |
|---|---|---|
| OpenGamma, *Interest Rate Instruments and Market Conventions Guide* | Documento sectorial de referencia | `opengamma2024conventions` |
| OpenGamma Strata (código de producción) | Convenciones estándar codificadas, verificadas en `StandardFixedIborSwapConventions` y `StandardFixedOvernightSwapConventions` | `opengamma2026strata` |
| ARRC / Fed de Nueva York | Cese de USD LIBOR el 30/06/2023 y adopción de SOFR | `arrc2023closing` |
| QuantLib | Base y calendario del índice SOFR (`ql/indexes/ibor/sofr.cpp`); herencia de la base de la pata fija (`ql/instruments/makeois.cpp`) | `quantlib2026` |

**Sobre citar código como fuente.** Strata y QuantLib son librerías de
producción, no publicaciones académicas. Se citan como evidencia de
implementación; la referencia de autoridad para la memoria es el documento de
convenciones de OpenGamma, que Strata señala como su propia fuente.

---

## Qué se entiende por «base estándar»

El conjunto de convenciones que el mercado aplica por defecto a un *swap* vanilla
sin necesidad de enunciarlas.

Aplica a **vencimientos de un año o superiores**. Por debajo del año el
instrumento sigue convenciones de mercado monetario —un único periodo, sin
cupones intermedios— y **queda fuera del alcance** de este trabajo.

Punto importante de diseño: **la convención no depende solo de la divisa, también
del plazo**. No es una tabla plana indexada por divisa, son reglas condicionadas.

---

## EUR

Verificado en `StandardFixedIborSwapConventions`. Cita literal del código:

> `EUR_FIXED_1Y_EURIBOR_3M` — *«EUR(1Y) vanilla fixed vs Euribor 3M swap. The
> fixed leg pays yearly with day count '30U/360'.»*
>
> `EUR_FIXED_1Y_EURIBOR_6M` — *«EUR(>1Y) vanilla fixed vs Euribor 6M swap. The
> fixed leg pays yearly with day count '30U/360'.»*

| Elemento | Vencimiento = 1Y | Vencimiento > 1Y |
|---|---|---|
| Pata fija: base | 30U/360 | 30U/360 |
| Pata fija: frecuencia | Anual (1Y) | Anual (1Y) |
| Pata flotante: índice | **EURIBOR 3M** | **EURIBOR 6M** |
| Pata flotante: base | ACT/360 | ACT/360 |
| Pata flotante: frecuencia | **Trimestral (3M)** | **Semestral (6M)** |
| Convención de días hábiles | *Modified Following* | *Modified Following* |
| Calendario | EUTA (TARGET) | EUTA (TARGET) |
| Curva de descuento | EUR-ESTR | EUR-ESTR |
| Curva de estimación | EUR-EURIBOR-3M | EUR-EURIBOR-6M |

**La base es `30U/360`**, la variante estadounidense, no un `30/360` genérico.

En EUR se mantiene la regla de que **la frecuencia de pago de la pata flotante
coincide con el tenor del índice**.

---

## USD

Aquí está el hallazgo que motivó esta verificación.

**En USD no existe ninguna convención de *swap* fijo contra SOFR con tenor.** Un
*swap* vanilla en dólares es hoy un **OIS**: la pata flotante capitaliza el tipo a
un día, sin fijaciones con plazo.

Verificado en `StandardFixedOvernightSwapConventions`:

> `USD_FIXED_1Y_SOFR_OIS` — *«USD fixed vs SOFR OIS swap for terms greater than
> one year. Both legs pay annually and use day count 'Act/360'. The spot date
> offset is 2 days and the payment date offset is 2 days.»*
>
> Método de devengo: `COMPOUNDED`.

| Elemento | Vencimiento ≥ 1Y |
|---|---|
| Pata fija: base | **ACT/360** |
| Pata fija: frecuencia | **Anual (1Y)** |
| Pata flotante: índice | **SOFR, capitalizado diariamente** |
| Pata flotante: base | ACT/360 |
| Pata flotante: frecuencia | **Anual (1Y)** |
| Pata flotante: tenor | **no aplica** |
| Desfase de contado | 2 días hábiles |
| Desfase de pago | 2 días hábiles |
| Calendario | US SOFR |
| Curva de descuento y estimación | USD-SOFR |

**La regla «frecuencia igual al tenor» NO aplica en USD.** No hay tenor.

### La convención incorrecta que se estaba usando, y de dónde venía

La propuesta anterior —pata fija semestral 30/360 contra SOFR 3M trimestral— no
existe en el mercado. Es la estructura de `USD_FIXED_6M_LIBOR_3M`, la convención
de **LIBOR**, con el nombre SOFR sustituido encima.

USD LIBOR cesó el **30 de junio de 2023** (`arrc2023closing`). La convención
existe todavía en las librerías por compatibilidad con operaciones heredadas, no
como estándar vigente.

---

## Consecuencia de diseño: los OIS pasan a ser producto soportado

**Decisión tomada el 21/09/2026.** Si el trabajo cubre USD, no hay alternativa:
todo *swap* vanilla en dólares es un OIS.

### Pendiente de corregir

**1. El orquestador.** `agents/orchestrator_agent.md` mantiene en su lista de
productos no soportados:

> *«An overnight index swap requested as its own product, with no tenor on the
> floating leg. A fixed-versus-`SOFR 3M` or fixed-versus-`SONIA 3M` swap is not
> this case and must be classified `IRS`.»*

Esa regla se escribió el 14/09/2026 para corregir dos falsos negativos, y
**presupone la existencia de un SOFR con tenor 3M que no existe**. Con la
convención real —SOFR anual capitalizado, sin tenor— el orquestador rechazaría un
*swap* USD legítimo.

**2. Los casos dorados USD.** `usd_payer_sofr` y `abreviado_usd` usan SOFR 3M
trimestral con pata fija semestral 30/360. No corresponde a ninguna convención
real y hay que rehacerlos.

**3. El esquema.** El campo `floating_leg.tenor` deja de ser universal: es
obligatorio en EUR y no aplica en USD. Hay que decidir si se modela como campo
opcional o si el tipo de pata flotante pasa a ser explícito (IBOR frente a
capitalización a un día).

### Lectura para la memoria

Es un resultado defendible, no un tropiezo. La transición del LIBOR a los tipos
libres de riesgo **cambió la estructura misma del producto**, no solo el nombre
del índice: un *swap* vanilla en dólares dejó de ser fijo-contra-IBOR-con-plazo y
pasó a ser fijo-contra-tipo-a-un-día-capitalizado. Un esquema de datos diseñado
sobre la intuición previa a 2023 modela un instrumento que ya no se negocia.

---

## GBP, fuera de alcance

`GBP_FIXED_1Y_SONIA_OIS` existe y está verificada (ambas patas anuales, ACT/365F,
desfases de 0 días), pero GBP queda excluido del alcance. El caso dorado
`gbp_receiver_sonia` debe retirarse o reescribirse.
