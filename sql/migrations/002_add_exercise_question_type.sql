-- 为 exercises 表增加题型字段，便于列表/详情展示与按题型筛选
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'exercises' AND column_name = 'question_type'
    ) THEN
        ALTER TABLE exercises ADD COLUMN question_type VARCHAR(30);
    END IF;
END $$;

-- 用该练习下首题的 type 回填已有数据
UPDATE exercises e
SET question_type = (
    SELECT q.type FROM questions q WHERE q.exercise_id = e.id ORDER BY q.created_at ASC LIMIT 1
)
WHERE e.question_type IS NULL;

CREATE INDEX IF NOT EXISTS idx_exercises_question_type ON exercises(question_type);
