CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    school VARCHAR(200),
    major VARCHAR(200),
    grade VARCHAR(50),
    age INTEGER,
    gender VARCHAR(20),
    question_type_preference VARCHAR(500),
    difficulty_preference VARCHAR(50),
    question_count INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS docs (
    id VARCHAR(36) PRIMARY KEY,
    owner_id VARCHAR(36) NOT NULL REFERENCES users(id),
    file_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_hash VARCHAR(64),
    file_size INT,
    status VARCHAR(20) NOT NULL DEFAULT 'uploaded',
    save_to_library BOOLEAN NOT NULL DEFAULT FALSE,
    parsed_school VARCHAR(200),
    parsed_major VARCHAR(200),
    parsed_course VARCHAR(200),
    parsed_summary TEXT,
    parsed_knowledge_points JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_docs_owner_id ON docs(owner_id);

CREATE TABLE IF NOT EXISTS exercises (
    id VARCHAR(36) PRIMARY KEY,
    owner_id VARCHAR(36) NOT NULL REFERENCES users(id),
    title VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'generating',
    difficulty VARCHAR(20) NOT NULL,
    count INT NOT NULL,
    question_type VARCHAR(30),
    source_doc_id VARCHAR(36) REFERENCES docs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exercises_owner_id ON exercises(owner_id);
CREATE INDEX IF NOT EXISTS idx_exercises_question_type ON exercises(question_type);
CREATE INDEX IF NOT EXISTS idx_exercises_source_doc_id ON exercises(source_doc_id);

CREATE TABLE IF NOT EXISTS questions (
    id VARCHAR(36) PRIMARY KEY,
    exercise_id VARCHAR(36) NOT NULL REFERENCES exercises(id),
    type VARCHAR(30) NOT NULL,
    stem TEXT NOT NULL,
    options JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_questions_exercise_id ON questions(exercise_id);

CREATE TABLE IF NOT EXISTS answers (
    id VARCHAR(36) PRIMARY KEY,
    question_id VARCHAR(36) NOT NULL REFERENCES questions(id),
    correct_answer TEXT NOT NULL,
    analysis TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_answers_question_id ON answers(question_id);

CREATE TABLE IF NOT EXISTS exercise_results (
    id VARCHAR(36) PRIMARY KEY,
    exercise_id VARCHAR(36) NOT NULL REFERENCES exercises(id),
    owner_id VARCHAR(36) NOT NULL REFERENCES users(id),
    score INT,
    correct_rate INT,
    result_details JSONB,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exercise_results_exercise_id ON exercise_results(exercise_id);
CREATE INDEX IF NOT EXISTS idx_exercise_results_owner_id ON exercise_results(owner_id);
