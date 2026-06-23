from __future__ import annotations

from . import ui_messages


def build_session_status_payload(phase: str) -> dict[str, str]:
    payload = {
        'summary': ui_messages.SESSION_STATUS_SUMMARY_IDLE,
        'action_text': ui_messages.SESSION_STATUS_ACTION_IDLE,
        'badge_name': 'sessionStatusBadgeIdle',
        'launch_hint': ui_messages.LAUNCH_STEP_HINT_IDLE,
    }
    if phase == ui_messages.SESSION_STATUS_PHASE_STARTING:
        payload.update({
            'summary': ui_messages.SESSION_STATUS_SUMMARY_STARTING,
            'action_text': ui_messages.SESSION_STATUS_ACTION_STARTING,
            'badge_name': 'sessionStatusBadgeStarting',
        })
    elif phase == ui_messages.SESSION_STATUS_PHASE_RUNNING:
        payload.update({
            'summary': ui_messages.SESSION_STATUS_SUMMARY_RUNNING,
            'action_text': ui_messages.SESSION_STATUS_ACTION_RUNNING,
            'badge_name': 'sessionStatusBadgeRunning',
            'launch_hint': ui_messages.LAUNCH_STEP_HINT_RUNNING,
        })
    elif phase == ui_messages.SESSION_STATUS_PHASE_STOPPING:
        payload.update({
            'summary': ui_messages.SESSION_STATUS_SUMMARY_STOPPING,
            'action_text': ui_messages.SESSION_STATUS_ACTION_STOPPING,
            'badge_name': 'sessionStatusBadgeStopping',
        })
    elif phase == ui_messages.SESSION_STATUS_PHASE_AUTO_STOPPING:
        payload.update({
            'summary': ui_messages.SESSION_STATUS_SUMMARY_AUTO_STOPPING,
            'action_text': ui_messages.SESSION_STATUS_ACTION_AUTO_STOPPING,
            'badge_name': 'sessionStatusBadgeStopping',
        })
    elif phase == ui_messages.SESSION_STATUS_PHASE_STOPPED:
        payload.update({
            'summary': ui_messages.SESSION_STATUS_SUMMARY_STOPPED,
            'action_text': ui_messages.SESSION_STATUS_ACTION_STOPPED,
            'badge_name': 'sessionStatusBadgeStopped',
        })
    elif phase == ui_messages.SESSION_STATUS_PHASE_DETACHED:
        payload.update({
            'summary': ui_messages.SESSION_STATUS_SUMMARY_DETACHED,
            'action_text': ui_messages.SESSION_STATUS_ACTION_DETACHED,
            'badge_name': 'sessionStatusBadgeDetached',
        })
    elif phase == ui_messages.SESSION_STATUS_PHASE_FAILED:
        payload.update({
            'summary': ui_messages.SESSION_STATUS_SUMMARY_FAILED,
            'action_text': ui_messages.SESSION_STATUS_ACTION_FAILED,
            'badge_name': 'sessionStatusBadgeFailed',
        })
    return payload
