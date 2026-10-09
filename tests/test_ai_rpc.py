"""Faults must stop isolated evaluations with bounded waits and evidence."""
import json
import sys
import time

import pytest

from scripts.ai_rpc import PolicyClient, RPCFailure


def worker(tmp_path, code, **kwargs):
    return PolicyClient([sys.executable, "-u", "-c", code], root=tmp_path,
                        failure_dir=tmp_path, **kwargs)


def test_startup_timeout_kills_worker_and_records_stage(tmp_path):
    started = time.perf_counter()
    with pytest.raises(RPCFailure) as error:
        worker(tmp_path, "import time; time.sleep(30)", startup_timeout=0.1)
    assert time.perf_counter() - started < 3
    assert error.value.record["stage"] == "startup"
    assert error.value.path.exists()


@pytest.mark.parametrize("fault", ["import time; time.sleep(30)", "raise SystemExit(2)",
                                   "print('invalid json', flush=True)"])
def test_query_fault_terminates_and_retains_request_evidence(tmp_path, fault):
    client = worker(tmp_path, "import sys; print('{\"ready\":true}', flush=True); sys.stdin.readline(); " + fault)
    started = time.perf_counter()
    with pytest.raises(RPCFailure) as error:
        client.query({"difficulty": 3, "mode": "clock"}, timeout=0.1)
    assert time.perf_counter() - started < 3
    assert error.value.record["request_id"] == 1
    assert client.process.poll() is not None
    assert json.loads(error.value.path.read_text())["request_sha256"]
    assert error.value.record["request"]["difficulty"] == 3
    client.close()


def test_large_stderr_cannot_deadlock_response(tmp_path):
    code = '''
import json, sys
print('{"ready":true}', flush=True)
for line in sys.stdin:
    request = json.loads(line)
    sys.stderr.write('x' * 200000)
    sys.stderr.flush()
    print(json.dumps({'request_id': request['request_id'], 'ok': True}), flush=True)
'''
    client = worker(tmp_path, code)
    try:
        assert client.query({}, timeout=3)["ok"]
        assert client.query({}, timeout=3)["request_id"] == 2
    finally:
        client.close()
    assert not client.log_path.exists()


def test_stuck_stdin_write_is_also_bounded(tmp_path):
    client = worker(tmp_path, "import time; print('{\"ready\":true}', flush=True); time.sleep(30)")
    with pytest.raises(RPCFailure):
        client.query({"payload": "x" * 1000000}, timeout=0.1)
    assert client.process.poll() is not None


def test_wrong_response_id_is_a_failure(tmp_path):
    client = worker(tmp_path, "import sys; print('{\"ready\":true}', flush=True); sys.stdin.readline(); print('{\"request_id\":99}', flush=True)")
    with pytest.raises(RPCFailure, match="ID differs"):
        client.query({}, timeout=1)


def test_launch_failure_has_evidence_and_closes_log(tmp_path):
    with pytest.raises(RPCFailure) as error:
        PolicyClient([str(tmp_path / "missing-worker")], root=tmp_path, failure_dir=tmp_path)
    assert error.value.record["stage"] == "startup"
    assert error.value.path.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal behavior")
def test_kill_fallback_for_worker_ignoring_terminate(tmp_path):
    client = worker(tmp_path, "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('{\"ready\":true}', flush=True); time.sleep(30)")
    started = time.perf_counter()
    with pytest.raises(RPCFailure):
        client.query({}, timeout=0.1)
    assert time.perf_counter() - started < 3
    assert client.process.poll() is not None
