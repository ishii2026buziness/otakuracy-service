-- otakuracy database schema
-- Use: sqlite3 /data/otakuracy.db < schema.sql

CREATE TABLE IF NOT EXISTS ip_registry (
    ip_id           TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    official_url    TEXT,
    status          TEXT NOT NULL DEFAULT 'candidate',  -- candidate/active/cooling/inactive/blocked
    activation_score REAL DEFAULT 0.0,
    last_event_seen_at TEXT,        -- ISO8601
    last_verified_at TEXT,
    domain_tags     TEXT DEFAULT '[]',        -- JSON array: anime/manga/vtuber/game
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ip_alias (
    alias_id  INTEGER PRIMARY KEY,
    ip_id     TEXT NOT NULL REFERENCES ip_registry(ip_id) ON DELETE CASCADE,
    alias     TEXT NOT NULL,
    lang      TEXT,    -- 'ja' / 'en' / null
    source    TEXT,    -- 'manami' / 'agent' / 'user'
    UNIQUE(ip_id, alias)
);

CREATE TABLE IF NOT EXISTS event (
    event_id            TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    summary             TEXT,
    category            TEXT,  -- popup_store/collab_cafe/live/exhibition/stage/campaign/online
    status              TEXT DEFAULT 'announced',  -- announced/onsale/sold_out/ended/cancelled
    start_at            TEXT,  -- ISO8601
    end_at              TEXT,
    tz                  TEXT DEFAULT 'Asia/Tokyo',
    venue_id            TEXT,
    area_code           TEXT,
    is_online           INTEGER DEFAULT 0,
    official_url        TEXT,
    primary_ticket_url  TEXT,
    hero_image_url      TEXT,
    price_min           INTEGER,
    price_max           INTEGER,
    currency            TEXT DEFAULT 'JPY',
    ticketing_type      TEXT DEFAULT 'unknown',  -- lottery/first_come/free/unknown
    source_confidence   REAL DEFAULT 0.5,
    first_seen_at       TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS event_source_record (
    source_record_id TEXT PRIMARY KEY,
    source_id        TEXT NOT NULL,   -- "eplus", "eventernote", etc.
    source_url       TEXT NOT NULL,
    fetched_at       TEXT NOT NULL,
    raw_title        TEXT,
    raw_date_text    TEXT,
    raw_venue_text   TEXT,
    raw_price_text   TEXT,
    raw_body         TEXT,
    extracted_by     TEXT DEFAULT 'scraping',  -- scraping/ai/hybrid
    confidence       REAL DEFAULT 1.0,
    parse_version    TEXT DEFAULT '1',
    event_id         TEXT,  -- FK to event (nullable until resolved)
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS event_ip_link (
    event_id      TEXT NOT NULL,
    ip_id         TEXT NOT NULL,
    relation_type TEXT DEFAULT 'primary',  -- primary/featured/cast_related/brand_related
    confidence    REAL DEFAULT 1.0,
    PRIMARY KEY (event_id, ip_id)
);

CREATE TABLE IF NOT EXISTS venue (
    venue_id   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    prefecture TEXT,
    area_code  TEXT,
    lat        REAL,
    lng        REAL
);

CREATE TABLE IF NOT EXISTS price_offer (
    offer_id       TEXT PRIMARY KEY,
    event_id       TEXT NOT NULL,
    label          TEXT,
    price          INTEGER,
    currency       TEXT DEFAULT 'JPY',
    sales_start_at TEXT,
    sales_end_at   TEXT,
    availability   TEXT,
    source_url     TEXT
);

-- Indexes for event
CREATE INDEX IF NOT EXISTS idx_event_start_at  ON event (start_at);
CREATE INDEX IF NOT EXISTS idx_event_status    ON event (status);
CREATE INDEX IF NOT EXISTS idx_event_category  ON event (category);

-- Indexes for event_source_record
CREATE INDEX IF NOT EXISTS idx_esr_source_id  ON event_source_record (source_id);
CREATE INDEX IF NOT EXISTS idx_esr_source_url ON event_source_record (source_url);
CREATE INDEX IF NOT EXISTS idx_esr_event_id   ON event_source_record (event_id);

-- Indexes for event_ip_link
CREATE INDEX IF NOT EXISTS idx_eil_ip_id    ON event_ip_link (ip_id);
CREATE INDEX IF NOT EXISTS idx_eil_event_id ON event_ip_link (event_id);

-- Indexes for ip_registry
CREATE INDEX IF NOT EXISTS idx_ip_status       ON ip_registry (status);
CREATE INDEX IF NOT EXISTS idx_ip_display_name ON ip_registry (display_name);

-- Indexes for ip_alias
CREATE INDEX IF NOT EXISTS idx_ip_alias_ip_id ON ip_alias (ip_id);
CREATE INDEX IF NOT EXISTS idx_ip_alias_alias  ON ip_alias (alias);

-- unresolvable: 検索済みだが特定不能なイベントのリンク先（event_ip_link.ip_id = 'unresolvable'）
INSERT OR IGNORE INTO ip_registry (ip_id, display_name, status, created_at, updated_at)
VALUES ('unresolvable', 'unresolvable', 'blocked', datetime('now'), datetime('now'));
