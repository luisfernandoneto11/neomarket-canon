# ADR: Modos de visualização GET /products/{id}

**Status:** Aceito

**Data:** 2025-06-25

## Contexto

O endpoint `GET /products/{id}` precisa retornar dados do produto com diferentes níveis de detalhe dependendo do status de moderação do produto. Produtos moderados devem retornar o payload completo, produtos bloqueados devem incluir o motivo de bloqueio e reports de campos, e produtos de outros vendedores devem retornar 404.

## Alternativas

1. **View único com if** (escolhido)
   - Um único endpoint com lógica condicional para determinar qual payload retornar
   - Mais simples de manter e menos propenso a erros

2. **Dois views diferentes**
   - Endpoints separados para produtos moderados vs bloqueados
   - Mais explícito, mas aumenta complexidade e risco de inconsistência

3. **Permission class**
   - Usar classes de permissão para controlar visibilidade
   - Mais flexível, mas adiciona camada de complexidade desnecessária

## Critérios

- **Legibilidade:** código fácil de entender e manter
- **Risco de vazar campos sensíveis:** minimizar exposição de dados internos

## Decisão

**View único com if** - mais simples e menor risco de erro.

## Consequências

- Endpoint único `/api/v1/b2b/products/{product_id}` com lógica baseada no status
- Payload varia conforme status: MODERATED (completo), BLOCKED (com blocking_reason e field_reports), outros (404)
- Menor superfície de ataque para vazamento de dados sensíveis