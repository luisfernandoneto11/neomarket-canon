# ADR 007: B2C Product Card — Serializer Separado

## Status

Aceito

## Context

O endpoint `GET /api/v1/products/{id}` serve compradores (B2C) e deve exibir detalhes do produto na página de detalhes. O mesmo produto possui campos sensíveis (cost_price, reserved_quantity) que nunca podem ser expostos ao B2C.

## Alternativas Consideradas

| Abordagem | Risco de Vazamento | Facilidade de Manutenção | Clareza |
|-----------|-------------------|-------------------------|---------|
| Serializer diferente para B2C (escolhido) | Impossível | Alta | Muito clara |
| View-level filter de campos | Alto (esquecimento) | Média | Média |
| Endpoint separado para B2C | Baixo | Baixa (duplicação) | Clara |

## Decisão

**Serializer separado para B2C** — mais seguro, mais claro, impossível vazar campo por esquecimento.

A classe `SKUCardResponse` em `schemas/product_card_schemas.py` define explicitamente apenas os campos seguros. Qualquer campo novo adicionado ao B2B não vaza automaticamente para B2C.

## Regras Importantes

### Segurança Crítica
- **NUNCA** retornar `cost_price` e `reserved_quantity` no response B2C
- Esses campos são dados internos do seller que não devem ser expostos

### Visibilidade
- Apenas produtos com `status=MODERATED` e `deleted=false` são visíveis
- Produto bloqueado (`is_hard_blocked=true`): retornar **404** (não 403)
  - 404 é melhor porque não revela que o produto existe mas está bloqueado

### Estoque
- SKU sem estoque (`active_quantity=0`): mostrar com `in_stock=false`
- Não omitir a SKU, apenas indicar indisponibilidade

### Discount
- Manter `discount` no response para frontend exibir preço riscado

### B2B Offline
- Quando o serviço B2B estiver indisponível: retornar **502/503**

## Implementação

- Endpoint: `GET /api/v1/products/{id}` em `apis/b2c/product_card.py`
- Schema: `ProductCardResponse` / `SKUCardResponse` em `schemas/product_card_schemas.py`
- Service: `ProductCardService` em `services/product_card_service.py`
- Testes: `tests/test_b2c_product_card.py` (14 testes, incluindo segurança crítica)

## Consequências

- Positivo: Segurança garantida por design (schema explícito)
- Positivo: Clareza — desenvolvedor vê imediatamente o que é exposto
- Positivo: Manutenibilidade — adicionar campo B2B não afeta B2C automaticamente
- Negativo: Leve duplicação de schema (B2B e B2C), mas aceitável pelo benefício