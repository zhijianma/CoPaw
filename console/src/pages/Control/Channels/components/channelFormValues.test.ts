import { describe, expect, it } from "vitest";

import { buildChannelFormValues } from "./channelFormValues";

describe("buildChannelFormValues", () => {
  it("编辑已有频道时保留启用状态和已有配置", () => {
    expect(
      buildChannelFormValues({
        enabled: false,
        app_id: "cli-existing",
        no_text_debounce: false,
      }),
    ).toMatchObject({
      enabled: false,
      app_id: "cli-existing",
      no_text_debounce: false,
    });
  });

  it("统一提供共享字段默认值", () => {
    expect(buildChannelFormValues({})).toMatchObject({
      enabled: true,
      show_tool_calls: true,
      show_tool_results: true,
      tool_call_max_length: 200,
      tool_result_max_length: 500,
      show_thinking: true,
      no_text_debounce: true,
    });
  });

  it("迁移旧 allowlist 策略到访问控制开关", () => {
    expect(
      buildChannelFormValues({
        dm_policy: "allowlist",
        group_policy: "allowlist",
      }),
    ).toMatchObject({
      access_control_dm: true,
      access_control_group: true,
    });
  });
});
