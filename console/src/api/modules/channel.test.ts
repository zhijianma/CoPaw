import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../request", () => ({ request: vi.fn() }));

import { request } from "../request";
import { channelApi } from "./channel";

describe("channelApi", () => {
  beforeEach(() => vi.mocked(request).mockReset());
  afterEach(() => vi.clearAllMocks());

  it("lists agent-owned Channel configurations", async () => {
    const channels = [
      {
        id: "telegram",
        type: "telegram",
        name: "Main",
        enabled: true,
        settings: {},
      },
    ];
    vi.mocked(request).mockResolvedValue(channels);

    await expect(channelApi.listChannels()).resolves.toEqual(channels);
    expect(request).toHaveBeenCalledWith("/config/channels");
  });

  it("creates a Channel configuration", async () => {
    const value = {
      id: "",
      type: "telegram",
      name: "Backup",
      enabled: false,
      settings: {},
    };
    const persisted = value;
    vi.mocked(request).mockResolvedValue(persisted);

    await expect(channelApi.createChannelConfig(value)).resolves.toEqual(
      persisted,
    );
    expect(request).toHaveBeenCalledWith("/config/channels", {
      method: "POST",
      body: JSON.stringify(value),
    });
  });

  it("gets and updates by encoded Channel type", async () => {
    const channel = {
      id: "telegram",
      type: "telegram",
      name: "Main",
      enabled: true,
      settings: {},
    };
    vi.mocked(request).mockResolvedValue(channel);

    await channelApi.getChannelConfig(channel.type);
    await channelApi.updateChannelConfig(channel.type, channel);

    expect(request).toHaveBeenNthCalledWith(1, "/config/channels/telegram");
    expect(request).toHaveBeenNthCalledWith(2, "/config/channels/telegram", {
      method: "PUT",
      body: JSON.stringify(channel),
    });
  });

  it("deletes by Channel type", async () => {
    vi.mocked(request).mockResolvedValue(undefined);

    await channelApi.deleteChannelConfig("telegram");

    expect(request).toHaveBeenCalledWith("/config/channels/telegram", {
      method: "DELETE",
    });
  });

  it("keeps Console on its Transport API", async () => {
    const consoleConfig = { enabled: true };
    vi.mocked(request).mockResolvedValue(consoleConfig);

    await channelApi.getConsoleConfig();
    await channelApi.updateConsoleConfig(consoleConfig as never);

    expect(request).toHaveBeenNthCalledWith(1, "/config/transports/console");
    expect(request).toHaveBeenNthCalledWith(2, "/config/transports/console", {
      method: "PUT",
      body: JSON.stringify(consoleConfig),
    });
  });

  it("lists types, catalog, and schemas", async () => {
    vi.mocked(request).mockResolvedValue([]);
    await channelApi.listChannelTypes();
    await channelApi.listChannelCatalog();
    await channelApi.listChannelSchemas();
    expect(request).toHaveBeenNthCalledWith(1, "/config/channels/types");
    expect(request).toHaveBeenNthCalledWith(2, "/config/channels/catalog");
    expect(request).toHaveBeenNthCalledWith(3, "/config/channels/schemas");
  });

  it("checks conflicts by Channel type", async () => {
    vi.mocked(request).mockResolvedValue({ conflict: false, agents: [] });
    await channelApi.checkChannelConflict("telegram", {
      enabled: true,
    } as never);
    expect(request).toHaveBeenCalledWith(
      "/config/channels/telegram/conflict-check",
      expect.anything(),
    );
  });

  it("builds QR-code URLs with encoded values", async () => {
    vi.mocked(request).mockResolvedValue({});
    await channelApi.getChannelQrcode("wechat", { scene: "login" });
    await channelApi.getChannelQrcodeStatus("wechat", "token with space", {
      scene: "login",
    });
    expect(vi.mocked(request).mock.calls[0][0]).toContain("scene=login");
    expect(vi.mocked(request).mock.calls[1][0]).toContain(
      "token%20with%20space",
    );
  });
});
