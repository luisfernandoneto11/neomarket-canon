-- Migration: Create product moderation tables for US-MOD-01
-- Description: Database schema for receiving product events from B2B for Moderation service

-- Enable UUID extension if not exists
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Migration: US-B2B-05 - Add moderation fields to products and skus tables
-- Description: Add blocking_reason, field_reports to products; cost_price, reserved_quantity to skus

-- Table: products (B2B product management)
CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description VARCHAR(2000),
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT'
        CHECK (status IN ('DRAFT', 'ON_MODERATION', 'MODERATED', 'BLOCKED', 'HARD_BLOCKED')),
    blocking_reason JSONB,
    field_reports JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- Table: skus (B2B product variants)
CREATE TABLE IF NOT EXISTS skus (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL,
    sku_code VARCHAR(50) NOT NULL UNIQUE,
    price NUMERIC(10, 2) NOT NULL CHECK (price > 0),
    cost_price NUMERIC(10, 2),
    image_url VARCHAR(1000),
    stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
    reserved_quantity INTEGER NOT NULL DEFAULT 0 CHECK (reserved_quantity >= 0),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    
    CONSTRAINT fk_product
        FOREIGN KEY (product_id) 
        REFERENCES products(id) 
        ON DELETE CASCADE
);

-- Table: product_blocking_reasons
-- Description: Reference table for product blocking reasons
CREATE TABLE product_blocking_reasons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    hard_block BOOLEAN NOT NULL DEFAULT FALSE
);

-- Table: product_moderation
-- Description: Main table for product moderation records
CREATE TABLE product_moderation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL UNIQUE,
    seller_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' 
        CHECK (status IN ('PENDING', 'IN_REVIEW', 'MODERATED', 'BLOCKED', 'HARD_BLOCKED')),
    queue_priority INTEGER NOT NULL DEFAULT 1 
        CHECK (queue_priority >= 1 AND queue_priority <= 4),
    json_before JSONB,
    json_after JSONB NOT NULL,
    blocking_reason_id UUID,
    moderator_id UUID,
    moderator_comment TEXT,
    date_created TIMESTAMP NOT NULL DEFAULT now(),
    date_updated TIMESTAMP NOT NULL DEFAULT now(),
    date_moderation TIMESTAMP,
    
    CONSTRAINT fk_blocking_reason 
        FOREIGN KEY (blocking_reason_id) 
        REFERENCES product_blocking_reasons(id) 
        ON DELETE SET NULL
);

-- Table: product_moderation_field_report
-- Description: Field-level reports for moderation issues
CREATE TABLE product_moderation_field_report (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_moderation_id UUID NOT NULL,
    field_name VARCHAR(50) NOT NULL 
        CHECK (field_name IN ('title', 'description', 'product_images', 'category', 'sku_name', 'sku_image', 'sku_price')),
    sku_id UUID,
    comment TEXT NOT NULL,
    date_created TIMESTAMP NOT NULL DEFAULT now(),
    
    CONSTRAINT fk_product_moderation 
        FOREIGN KEY (product_moderation_id) 
        REFERENCES product_moderation(id) 
        ON DELETE CASCADE
);

-- Table: moderation_events
-- Description: Idempotency tracking for moderation decisions from B2B
CREATE TABLE IF NOT EXISTS moderation_events (
    idempotency_key UUID PRIMARY KEY,
    product_id UUID NOT NULL,
    processed_at TIMESTAMP NOT NULL DEFAULT now(),
    result JSONB NOT NULL
);

-- Indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_product_moderation_product_id ON product_moderation(product_id);
CREATE INDEX IF NOT EXISTS idx_product_moderation_seller_id ON product_moderation(seller_id);
CREATE INDEX IF NOT EXISTS idx_product_moderation_status ON product_moderation(status);
CREATE INDEX IF NOT EXISTS idx_product_moderation_queue_priority ON product_moderation(queue_priority);
CREATE INDEX IF NOT EXISTS idx_product_moderation_date_updated ON product_moderation(date_updated);
CREATE INDEX IF NOT EXISTS idx_field_report_moderation_id ON product_moderation_field_report(product_moderation_id);
CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);
CREATE INDEX IF NOT EXISTS idx_skus_product_id ON skus(product_id);
CREATE INDEX IF NOT EXISTS idx_skus_sku_code ON skus(sku_code);
CREATE INDEX IF NOT EXISTS idx_moderation_events_product_id ON moderation_events(product_id);

-- Seed data for product_blocking_reasons
INSERT INTO product_blocking_reasons (id, title, hard_block) VALUES
    ('a7b8c9d0-1234-5678-ef01-890123456789', 'Описание не соответствует товару', FALSE),
    ('b8c9d0e1-2345-6789-f012-901234567890', 'Изображение не соответствует товару', FALSE),
    ('c9d0e1f2-3456-7890-0123-012345678901', 'Некорректная категория товара', FALSE),
    ('d0e1f2a3-4567-8901-1234-123456789012', 'Недостаточно информации о товаре', FALSE),
    ('e1f2a3b4-5678-9012-2345-234567890123', 'Нецензурные или оскорбительные материалы', FALSE),
    ('f2a3b4c5-6789-0123-3456-345678901234', 'Дублирование существующего товара', FALSE),
    ('a3b4c5d6-7890-1234-4567-456789012345', 'Некорректная цена', FALSE),
    ('b4c5d6e7-8901-2345-5678-567890123456', 'Контрафактный товар', TRUE),
    ('c5d6e7f8-9012-3456-6789-678901234567', 'Товар запрещён к продаже на территории РФ', TRUE),
    ('d6e7f8a9-0123-4567-7890-789012345678', 'Товар нарушает авторские права', TRUE);

-- Comments for documentation
COMMENT ON TABLE product_blocking_reasons IS 'Reference table for product blocking reasons';
COMMENT ON TABLE product_moderation IS 'Main table for product moderation records';
COMMENT ON TABLE product_moderation_field_report IS 'Field-level reports for moderation issues';
COMMENT ON TABLE products IS 'B2B products for moderation';
COMMENT ON TABLE skus IS 'B2B product variants (SKUs)';

COMMENT ON COLUMN product_moderation.json_before IS 'Product state BEFORE changes (null for new products)';
COMMENT ON COLUMN product_moderation.json_after IS 'Current product state (GET /api/v1/products/{id} from B2B)';
COMMENT ON COLUMN product_moderation.queue_priority IS 'Queue number: 1-4 (calculated during event processing)';
COMMENT ON COLUMN product_moderation.status IS 'PENDING, IN_REVIEW, MODERATED, BLOCKED, HARD_BLOCKED';
COMMENT ON COLUMN product_moderation_field_report.field_name IS 'Allowed: title, description, product_images, category, sku_name, sku_image, sku_price';
COMMENT ON COLUMN product_moderation_field_report.sku_id IS 'Specific SKU ID (null = issue with product, not SKU)';
COMMENT ON COLUMN products.blocking_reason IS 'Blocking reason: {title, description}';
COMMENT ON COLUMN products.field_reports IS 'Field reports: [{field, message, value, suggestion}]';
COMMENT ON COLUMN products.status IS 'DRAFT, ON_MODERATION, MODERATED, BLOCKED, HARD_BLOCKED';
COMMENT ON COLUMN skus.cost_price IS 'SKU cost price (optional)';
COMMENT ON COLUMN skus.reserved_quantity IS 'Reserved stock quantity';
