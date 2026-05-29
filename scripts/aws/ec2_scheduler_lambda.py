"""
EC2 Start/Stop — EventBridge Scheduler → Lambda.

환경변수:
  INSTANCE_ID  — i-0123456789abcdef0 (단일 인스턴스)
  ACTION       — 이벤트 입력 {"action":"start"|"stop"} 가 없을 때 기본값

배포: scripts/aws/README.md 참고
"""
from __future__ import annotations

import os
from typing import Any

import boto3


def _instance_id() -> str:
    raw = (os.environ.get("INSTANCE_ID") or "").strip()
    if not raw:
        raise RuntimeError("INSTANCE_ID env required")
    return raw


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    action = str((event or {}).get("action") or os.environ.get("ACTION") or "stop").strip().lower()
    iid = _instance_id()
    ec2 = boto3.client("ec2")
    if action == "start":
        ec2.start_instances(InstanceIds=[iid])
        return {"action": "start", "instance_id": iid}
    if action == "stop":
        ec2.stop_instances(InstanceIds=[iid])
        return {"action": "stop", "instance_id": iid}
    raise ValueError(f"unknown action: {action}")
