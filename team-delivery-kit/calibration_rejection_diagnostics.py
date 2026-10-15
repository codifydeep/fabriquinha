"""Closed diagnostic codes only; never persist exception text or model values."""
MESSAGE_CODES={
    'incomplete calibration stream':'stream_incomplete',
    'calibration data after terminal':'stream_after_done',
    'provider calibration stream error':'stream_provider_error',
    'ambiguous calibration choice':'ambiguous_choice',
    'legacy calibration function call forbidden':'legacy_function_call',
    'calibration data after finish':'stream_after_finish',
    'bounded tool index required':'tool_index_invalid',
    'one calibration choice required':'ambiguous_choice',
    'actual readonly tool turn required':'tool_finish_invalid',
    'calibration tool must be a bounded frozen read':'tool_read_invalid',
    'terminal calibration JSON required':'artifact_finish_invalid',
    'bounded calibration artifact required':'artifact_size_invalid',
    'duplicate JSON key':'json_duplicate_key',
}
CODE_CATEGORIES={**{v:'invalid_transport_or_tool' for v in MESSAGE_CODES.values()},
    'unclassified_transport':'invalid_transport_or_tool','invalid_json':'invalid_json','schema_violation':'schema_violation'}


def failure_code(error,category):
    if category in ('schema_violation','invalid_json'):return category
    # Exact equality against fixed source strings, never an arbitrary message
    # substring, schema instance, path or exception repr in the durable receipt.
    return MESSAGE_CODES.get(str(error),'unclassified_transport') if type(error) is ValueError else 'unclassified_transport'
