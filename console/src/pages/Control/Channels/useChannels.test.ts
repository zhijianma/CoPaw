import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useChannels } from "./useChannels";

vi.mock("../../../api", () => ({
  default: {
    listChannels: vi.fn(),
    getConsoleConfig: vi.fn(),
    listChannelTypes: vi.fn(),
    listChannelCatalog: vi.fn(),
    listChannelSchemas: vi.fn(),
  },
}));
vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: vi.fn(() => ({ selectedAgent: "agent-1" })),
}));

import api from "../../../api";

describe("useChannels", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listChannels).mockResolvedValue([]);
    vi.mocked(api.getConsoleConfig).mockResolvedValue({
      enabled: true,
    } as never);
    vi.mocked(api.listChannelTypes).mockResolvedValue([]);
    vi.mocked(api.listChannelCatalog).mockResolvedValue([]);
    vi.mocked(api.listChannelSchemas).mockResolvedValue({});
  });

  it("loads channels, Console, types, and catalog", async () => {
    vi.mocked(api.listChannels).mockResolvedValue([
      {
        id: "telegram",
        type: "telegram",
        name: "Main",
        enabled: true,
        settings: {},
      },
    ]);
    vi.mocked(api.listChannelTypes).mockResolvedValue(["telegram", "console"]);
    vi.mocked(api.listChannelCatalog).mockResolvedValue([
      {
        key: "console",
        order: 0,
        surface: "web",
        supports_access_control: false,
        supports_streaming: false,
      },
      {
        key: "telegram",
        order: 50,
        surface: "channel",
        supports_access_control: true,
        supports_streaming: true,
      },
    ]);

    const { result } = renderHook(() => useChannels());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.channels[0].type).toBe("telegram");
    expect(result.current.consoleConfig.enabled).toBe(true);
    expect(result.current.orderedTypes).toEqual(["telegram"]);
    expect(result.current.isBuiltin("telegram")).toBe(true);
  });

  it("keeps multiple configurations of the same type by id", async () => {
    const { result } = renderHook(() => useChannels());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.applyChannelConfig({
        id: "telegram",
        type: "telegram",
        name: "Main",
        enabled: true,
        settings: {},
      });
      result.current.applyChannelConfig({
        id: "telegram-backup",
        type: "telegram",
        name: "Backup",
        enabled: false,
        settings: {},
      });
    });

    expect(result.current.channels).toHaveLength(2);
    expect(result.current.channels[1].name).toBe("Backup");
  });

  it("does not let an older fetch overwrite a saved config", async () => {
    let resolveRefresh: ((value: never[]) => void) | undefined;
    vi.mocked(api.listChannels)
      .mockResolvedValueOnce([])
      .mockImplementationOnce(
        () => new Promise((resolve) => (resolveRefresh = resolve)),
      );
    const { result } = renderHook(() => useChannels());
    await waitFor(() => expect(result.current.loading).toBe(false));

    let refresh: Promise<void> | undefined;
    act(() => {
      refresh = result.current.fetchChannels();
      result.current.applyChannelConfig({
        id: "telegram",
        type: "telegram",
        name: "Saved",
        enabled: true,
        settings: {},
      });
    });
    await act(async () => {
      resolveRefresh?.([]);
      await refresh;
    });

    expect(result.current.channels[0].name).toBe("Saved");
  });
});
