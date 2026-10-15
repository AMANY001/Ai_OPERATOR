from state import create_task, get_task, upsert_step, get_step, update_step, list_steps, append_audit, get_audit_log


def test_task_and_steps_persist(tmp_path):
    db = tmp_path / "state.db"
    task_id = create_task("test goal", {"mode": "test"}, db_path=db)
    first = upsert_step(task_id, "search", "Search", "search_web", "pending", db_path=db)
    same = upsert_step(task_id, "search", "Search again", "search_web", "pending", db_path=db)
    assert first["id"] == same["id"]
    update_step(task_id, "search", "done", {"count": 2}, db_path=db)
    assert get_task(task_id, db_path=db)["goal"] == "test goal"
    assert get_step(task_id, "search", db_path=db)["result_json"] == {"count": 2}
    assert len(list_steps(task_id, db_path=db)) == 1
    append_audit(task_id, "unit_test", {"ok": True}, db_path=db)
    assert get_audit_log(task_id, db_path=db)[0]["event"] == "unit_test"
