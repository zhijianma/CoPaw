import { useState, useEffect, useCallback, useMemo } from "react";
import api from "../../../api";
import type {
  ChannelDefinition,
  ChannelSchema,
} from "../../../api/modules/channel";
import { useAgentStore } from "../../../stores/agentStore";

export function useChannels() {
  const { selectedAgent } = useAgentStore();
  const [channels, setChannels] = useState<
    Record<string, Record<string, unknown>>
  >({});
  const [channelTypes, setChannelTypes] = useState<string[]>([]);
  const [channelCatalog, setChannelCatalog] = useState<ChannelDefinition[]>([]);
  const [channelSchemas, setChannelSchemas] = useState<
    Record<string, ChannelSchema>
  >({});
  const [loading, setLoading] = useState(true);

  const fetchChannels = useCallback(async () => {
    setLoading(true);
    try {
      const [data, types, catalog] = await Promise.all([
        api.listChannels(),
        api.listChannelTypes(),
        api.listChannelCatalog(),
      ]);
      if (data)
        setChannels(data as unknown as Record<string, Record<string, unknown>>);
      if (types) setChannelTypes(types);
      if (catalog) setChannelCatalog(catalog);
    } catch (error) {
      console.error("❌ Failed to load channels:", error);
    } finally {
      setLoading(false);
    }
    // Fetch schemas separately so failures don't block core channel loading
    try {
      const schemas = await api.listChannelSchemas();
      if (schemas) setChannelSchemas(schemas);
    } catch {
      // Plugin system may not be available; non-critical
    }
  }, []);

  useEffect(() => {
    fetchChannels();
  }, [fetchChannels, selectedAgent]);

  // Built-in order is owned by the backend catalog; plugins remain last.
  const builtinOrder = useMemo(
    () =>
      [...channelCatalog]
        .sort((left, right) => left.order - right.order)
        .map((item) => item.key),
    [channelCatalog],
  );

  const orderedKeys = useMemo(
    () => [
      ...builtinOrder.filter((k) => channelTypes.includes(k)),
      ...channelTypes.filter((k) => !builtinOrder.includes(k)),
    ],
    [builtinOrder, channelTypes],
  );

  // Read isBuiltin from API response
  const isBuiltin = useCallback(
    (key: string) => Boolean(channels[key]?.isBuiltin),
    [channels],
  );

  return {
    channels,
    channelTypes,
    channelCatalog,
    channelSchemas,
    orderedKeys,
    isBuiltin,
    loading,
    fetchChannels,
  };
}
