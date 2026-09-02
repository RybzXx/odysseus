import os

db_path = os.path.join('core', 'database.py')
with open(db_path, 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Add agent_summary column to Project model
if "agent_summary   = Column(Text" not in code:
    code = code.replace(
        "    task_completed = Column(Integer, default=0)",
        "    task_completed = Column(Integer, default=0)\n    agent_summary   = Column(Text, nullable=True)                 # Short AI-generated overview"
    )

# 2. Add migration function
migration_code = """
def _migrate_project_agent_summary():
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            try:
                conn.execute(text("SELECT agent_summary FROM projects LIMIT 1"))
            except Exception:
                try:
                    conn.execute(text("ALTER TABLE projects ADD COLUMN agent_summary TEXT"))
                    conn.commit()
                except Exception as e:
                    logger.warning(f"Failed to migrate projects table for agent_summary: {e}")
"""
if "def _migrate_project_agent_summary" not in code:
    code = code.replace("def init_db():", migration_code + "\ndef init_db():")
    code = code.replace("    _migrate_model_endpoints()", "    _migrate_model_endpoints()\n    _migrate_project_agent_summary()")

with open(db_path, 'w', encoding='utf-8') as f:
    f.write(code)

print("database.py updated.")
