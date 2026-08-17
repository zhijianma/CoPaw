export function buildChannelFormValues(
  channelConfig: Record<string, unknown>,
): Record<string, unknown> {
  return {
    ...channelConfig,
    enabled: channelConfig.enabled ?? true,
    access_control_dm:
      channelConfig.access_control_dm ||
      channelConfig.dm_policy === "allowlist",
    access_control_group:
      channelConfig.access_control_group ||
      channelConfig.group_policy === "allowlist",
    show_tool_calls: channelConfig.show_tool_calls ?? true,
    show_tool_results: channelConfig.show_tool_results ?? true,
    tool_call_max_length: channelConfig.tool_call_max_length ?? 200,
    tool_result_max_length: channelConfig.tool_result_max_length ?? 500,
    show_thinking: channelConfig.show_thinking ?? true,
    no_text_debounce: channelConfig.no_text_debounce ?? true,
  };
}
