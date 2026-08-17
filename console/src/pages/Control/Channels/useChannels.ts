import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "../../../api";
import type {
  ChannelDefinition,
  ChannelSchema,
} from "../../../api/modules/channel";
import type { ChannelConfig } from "../../../api/types";
import { useAgentStore } from "../../../stores/agentStore";

export function useChannels() {
  const { selectedAgent } = useAgentStore();
  const [channels, setChannels] = useState<ChannelConfig[]>([]);
  const [consoleConfig, setConsoleConfig] = useState<
    Record<string, unknown>
  >({});
  const [channelTypes, setChannelTypes] = useState<string[]>([]);
  const [channelCatalog, setChannelCatalog] = useState<ChannelDefinition[]>([]);
  const [channelSchemas, setChannelSchemas] = useState<
    Record<string, ChannelSchema>
  >({});
  const [loading, setLoading] = useState(true);
  const revision = useRef(0);

  const fetchChannels = useCallback(async () => {
    const revisionAtStart = revision.current;
    setLoading(true);
    try {
      const [savedChannels, savedConsole, types, catalog] = await Promise.all([
        api.listChannels(),
        api.getConsoleConfig(),
        api.listChannelTypes(),
        api.listChannelCatalog(),
      ]);
      if (revisionAtStart === revision.current) {
        setChannels(savedChannels);
        setConsoleConfig({ ...savedConsole });
      }
      setChannelTypes(types);
      setChannelCatalog(catalog);
    } catch (error) {
      console.error("Failed to load channels:", error);
    } finally {
      setLoading(false);
    }
    try {
      setChannelSchemas(await api.listChannelSchemas());
    } catch {
      // Plugin schemas are optional.
    }
  }, []);

  useEffect(() => {
    fetchChannels();
  }, [fetchChannels, selectedAgent]);

  const orderedTypes = useMemo(() => {
    const builtin = [...channelCatalog]
      .sort((left, right) => left.order - right.order)
      .map((item) => item.key)
      .filter((key) => key !== "console");
    return [
      ...builtin.filter((key) => channelTypes.includes(key)),
      ...channelTypes.filter(
        (key) => key !== "console" && !builtin.includes(key),
      ),
    ];
  }, [channelCatalog, channelTypes]);

  const isBuiltin = useCallback(
    (type: string) =>
      channelCatalog.some((definition) => definition.key === type),
    [channelCatalog],
  );

  const applyChannelConfig = useCallback((value: ChannelConfig) => {
    revision.current += 1;
    setChannels((current) => {
      const index = current.findIndex((item) => item.type === value.type);
      if (index < 0) return [...current, value];
      return current.map((item) =>
        item.type === value.type ? value : item,
      );
    });
  }, []);

  const removeChannelConfig = useCallback((channelType: string) => {
    revision.current += 1;
    setChannels((current) =>
      current.filter((item) => item.type !== channelType),
    );
  }, []);

  const applyConsoleConfig = useCallback((value: Record<string, unknown>) => {
    revision.current += 1;
    setConsoleConfig(value);
  }, []);

  return {
    channels,
    consoleConfig,
    channelCatalog,
    channelSchemas,
    orderedTypes,
    isBuiltin,
    loading,
    fetchChannels,
    applyChannelConfig,
    removeChannelConfig,
    applyConsoleConfig,
  };
}
