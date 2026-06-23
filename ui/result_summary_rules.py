from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResultSummaryCategoryRule:
    key: str
    section_key: str
    total_hits_key: str
    overview_label: str
    note_section_title: str
    limit: int
    total_template: str
    unique_total_template: str
    recent_title_template: str
    extractor_name: str


def build_result_summary_category_rules(ui_messages_module) -> tuple[ResultSummaryCategoryRule, ...]:
    return (
        ResultSummaryCategoryRule(
            key='urls',
            section_key='urls',
            total_hits_key='url_total_hits',
            overview_label='URL/Network',
            note_section_title=ui_messages_module.RESULT_SUMMARY_NOTE_SECTION_URL,
            limit=8,
            total_template=ui_messages_module.RESULT_SUMMARY_URL_TOTAL,
            unique_total_template=ui_messages_module.RESULT_SUMMARY_URL_UNIQUE_TOTAL,
            recent_title_template=ui_messages_module.RESULT_SUMMARY_URL_RECENT_TITLE,
            extractor_name='_extract_result_summary_urls',
        ),
        ResultSummaryCategoryRule(
            key='activities',
            section_key='activities',
            total_hits_key='activity_total_hits',
            overview_label='Activity',
            note_section_title=ui_messages_module.RESULT_SUMMARY_NOTE_SECTION_ACTIVITY,
            limit=8,
            total_template=ui_messages_module.RESULT_SUMMARY_ACTIVITY_TOTAL,
            unique_total_template=ui_messages_module.RESULT_SUMMARY_ACTIVITY_UNIQUE_TOTAL,
            recent_title_template=ui_messages_module.RESULT_SUMMARY_ACTIVITY_RECENT_TITLE,
            extractor_name='_extract_result_summary_activities',
        ),
        ResultSummaryCategoryRule(
            key='jni_items',
            section_key='jni_items',
            total_hits_key='jni_total_hits',
            overview_label='JNI',
            note_section_title=ui_messages_module.RESULT_SUMMARY_NOTE_SECTION_JNI,
            limit=8,
            total_template=ui_messages_module.RESULT_SUMMARY_JNI_TOTAL,
            unique_total_template=ui_messages_module.RESULT_SUMMARY_JNI_UNIQUE_TOTAL,
            recent_title_template=ui_messages_module.RESULT_SUMMARY_JNI_RECENT_TITLE,
            extractor_name='_extract_result_summary_jni_registrations',
        ),
        ResultSummaryCategoryRule(
            key='anti_frida_items',
            section_key='anti_frida_items',
            total_hits_key='anti_frida_total_hits',
            overview_label='Anti-Frida',
            note_section_title=ui_messages_module.RESULT_SUMMARY_NOTE_SECTION_ANTI_FRIDA,
            limit=8,
            total_template=ui_messages_module.RESULT_SUMMARY_ANTI_FRIDA_TOTAL,
            unique_total_template=ui_messages_module.RESULT_SUMMARY_ANTI_FRIDA_UNIQUE_TOTAL,
            recent_title_template=ui_messages_module.RESULT_SUMMARY_ANTI_FRIDA_RECENT_TITLE,
            extractor_name='_extract_result_summary_anti_frida_hits',
        ),
        ResultSummaryCategoryRule(
            key='root_items',
            section_key='root_items',
            total_hits_key='root_total_hits',
            overview_label='Root',
            note_section_title=ui_messages_module.RESULT_SUMMARY_NOTE_SECTION_ROOT,
            limit=8,
            total_template=ui_messages_module.RESULT_SUMMARY_ROOT_TOTAL,
            unique_total_template=ui_messages_module.RESULT_SUMMARY_ROOT_UNIQUE_TOTAL,
            recent_title_template=ui_messages_module.RESULT_SUMMARY_ROOT_RECENT_TITLE,
            extractor_name='_extract_result_summary_root_hits',
        ),
        ResultSummaryCategoryRule(
            key='vpn_items',
            section_key='vpn_items',
            total_hits_key='vpn_total_hits',
            overview_label='VPN',
            note_section_title=ui_messages_module.RESULT_SUMMARY_NOTE_SECTION_VPN,
            limit=8,
            total_template=ui_messages_module.RESULT_SUMMARY_VPN_TOTAL,
            unique_total_template=ui_messages_module.RESULT_SUMMARY_VPN_UNIQUE_TOTAL,
            recent_title_template=ui_messages_module.RESULT_SUMMARY_VPN_RECENT_TITLE,
            extractor_name='_extract_result_summary_vpn_hits',
        ),
    )
