import { useCallback, useEffect, useMemo, useState } from "react";
import { Form } from "@agentscope-ai/design";
import { Badge, Button, Space } from "antd";
import { AuditOutlined, SafetyOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

import api from "../../../api";
import type { ChannelConfig } from "../../../api/types";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  AccessControlDrawer,
  ChannelAvailableItem,
  ChannelCard,
  ChannelDrawer,
  PendingApprovalsDrawer,
  getChannelLabel,
  type ChannelKey,
} from "./components";
import { buildChannelFormValues } from "./components/channelFormValues";
import { useChannels } from "./useChannels";
import styles from "./index.module.less";

type FilterType = "all" | "builtin" | "custom";

function ChannelsPage() {
  const { t } = useTranslation();
  const { message, modal } = useAppMessage();
  const {
    channels,
    consoleConfig,
    orderedTypes,
    channelCatalog,
    channelSchemas,
    isBuiltin,
    loading,
    applyChannelConfig,
    removeChannelConfig,
    applyConsoleConfig,
  } = useChannels();
  const [filter, setFilter] = useState<FilterType>("all");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [activeType, setActiveType] = useState<ChannelKey | null>(null);
  const [activeInstanceId, setActiveInstanceId] = useState<string | null>(null);
  const [activeConfigured, setActiveConfigured] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [aclDrawerOpen, setAclDrawerOpen] = useState(false);
  const [pendingDrawerOpen, setPendingDrawerOpen] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [form] = Form.useForm<any>();

  const fetchPendingCount = useCallback(async () => {
    try {
      setPendingCount((await api.getAclAllPending()).length);
    } catch {
      // Pending approvals are optional on this page.
    }
  }, []);

  useEffect(() => {
    fetchPendingCount();
  }, [fetchPendingCount]);

  const visibleChannels = useMemo(
    () =>
      channels.filter((channel) => {
        if (filter === "builtin") return isBuiltin(channel.type);
        if (filter === "custom") return !isBuiltin(channel.type);
        return true;
      }),
    [filter, channels, isBuiltin],
  );
  const enabledChannels = visibleChannels.filter((item) => item.enabled);
  const disabledChannels = visibleChannels.filter((item) => !item.enabled);
  const showConsole = filter !== "custom";
  const consoleEnabled = consoleConfig.enabled === true;
  const enabledCount =
    enabledChannels.length + (showConsole && consoleEnabled ? 1 : 0);

  const openForm = (
    type: ChannelKey,
    configured: boolean,
    config: Record<string, unknown>,
    name: string,
    instanceId: string | null = null,
  ) => {
    setActiveType(type);
    setActiveInstanceId(instanceId);
    setActiveConfigured(configured);
    form.resetFields();
    form.setFieldsValue(
      buildChannelFormValues({ ...config, configuration_name: name }),
    );
    setDrawerOpen(true);
  };

  const openChannel = (channel: ChannelConfig) => {
    openForm(
      channel.type as ChannelKey,
      true,
      { ...channel.settings, enabled: channel.enabled },
      channel.name,
      channel.id,
    );
  };

  const openNewChannel = (type: string) => {
    const label = getChannelLabel(type as ChannelKey, t);
    openForm(type as ChannelKey, false, { enabled: true }, label);
  };

  const closeDrawer = () => {
    setDrawerOpen(false);
    setActiveType(null);
    setActiveInstanceId(null);
    setActiveConfigured(false);
  };

  const handleSubmit = async (values: Record<string, unknown>) => {
    if (!activeType) return;
    const { configuration_name, isBuiltin: _builtin, ...settings } = values;
    const name = String(configuration_name || getChannelLabel(activeType, t));
    setSaving(true);
    try {
      if (activeType === "console") {
        const persisted = await api.updateConsoleConfig(settings as never);
        applyConsoleConfig({ ...persisted });
      } else {
        const enabled = settings.enabled === true;
        delete settings.enabled;
        if (enabled) {
          const conflict = await api.checkChannelConflict(activeType, {
            ...settings,
            enabled,
            _instance_id: activeInstanceId || "",
          } as never);
          if (conflict.conflict) {
            message.error(t("channels.botConflictTitle"));
            return;
          }
        }
        const value = {
          id: activeInstanceId || "",
          type: activeType,
          name,
          enabled,
          settings,
        };
        const persisted = activeConfigured
          ? await api.updateChannelConfig(activeInstanceId!, value)
          : await api.createChannelConfig(value);
        applyChannelConfig(persisted);
      }
      closeDrawer();
      message.success(t("channels.configSaved"));
    } catch (error) {
      console.error("Failed to save Channel configuration:", error);
      message.error(t("channels.configFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = () => {
    if (
      !activeType ||
      !activeInstanceId ||
      activeType === "console" ||
      !activeConfigured
    )
      return;
    modal.confirm({
      centered: true,
      title: t("common.delete"),
      content: t("channels.deleteConfirm"),
      okButtonProps: { danger: true },
      onOk: async () => {
        setDeleting(true);
        try {
          await api.deleteChannelConfig(activeInstanceId);
          removeChannelConfig(activeInstanceId);
          closeDrawer();
        } finally {
          setDeleting(false);
        }
      },
    });
  };

  const tabs: { key: FilterType; label: string }[] = [
    { key: "all", label: t("channels.filterAll") },
    { key: "builtin", label: t("channels.builtin") },
    { key: "custom", label: t("channels.custom") },
  ];
  const activeConfig = activeConfigured
    ? channels.find((item) => item.id === activeInstanceId)
    : undefined;
  const primaryHasSecondaries = Boolean(
    activeConfig &&
      activeConfig.id === activeConfig.type &&
      channels.some(
        (item) =>
          item.type === activeConfig.type && item.id !== activeConfig.id,
      ),
  );

  return (
    <div className={styles.channelsPage}>
      <PageHeader
        className={styles.pageHeader}
        items={[{ title: t("nav.control") }, { title: t("channels.title") }]}
        center={
          <div className={styles.filterTabs}>
            {tabs.map(({ key, label }) => (
              <button
                key={key}
                className={`${styles.filterTab} ${
                  filter === key ? styles.filterTabActive : ""
                }`}
                onClick={() => setFilter(key)}
              >
                {label}
              </button>
            ))}
          </div>
        }
        extra={
          <Space size={8}>
            <Badge dot={pendingCount > 0} offset={[-4, 4]}>
              <Button
                icon={<AuditOutlined />}
                onClick={() => setPendingDrawerOpen(true)}
              >
                {t("channels.pendingApprovals")}
              </Button>
            </Badge>
            <Button
              icon={<SafetyOutlined />}
              onClick={() => setAclDrawerOpen(true)}
            >
              {t("channels.manageAccessControl")}
            </Button>
          </Space>
        }
      />
      <div className={styles.channelsContainer}>
        {loading ? (
          <div className={styles.loading}>{t("channels.loading")}</div>
        ) : (
          <>
            <div className={styles.panelSection}>
              <div className={styles.panelTitle}>
                <span className={styles.panelDotGreen} />
                {t("channels.enabledSection")}
                <span className={styles.panelCount}>
                  {t("channels.enabledCount", { count: enabledCount })}
                </span>
              </div>
              <div className={styles.channelsGrid}>
                {showConsole && consoleEnabled && (
                  <ChannelCard
                    channelKey="console"
                    displayName="Console"
                    config={{ ...consoleConfig, isBuiltin: true }}
                    onClick={() =>
                      openForm("console", true, consoleConfig, "Console")
                    }
                  />
                )}
                {enabledChannels.map((channel) => (
                  <ChannelCard
                    key={channel.id}
                    channelKey={channel.type as ChannelKey}
                    displayName={channel.name}
                    config={{
                      ...channel.settings,
                      enabled: channel.enabled,
                      isBuiltin: isBuiltin(channel.type),
                    }}
                    iconUrl={channelSchemas[channel.type]?.icon}
                    onClick={() => openChannel(channel)}
                  />
                ))}
              </div>
            </div>
            <div className={styles.panelSectionDashed}>
              <div className={styles.panelTitle}>
                <span className={styles.panelDotGray} />
                {t("channels.availableSection")}
              </div>
              {showConsole && !consoleEnabled && (
                <div className={styles.channelsGrid}>
                  <ChannelCard
                    channelKey="console"
                    displayName="Console"
                    config={{ ...consoleConfig, isBuiltin: true }}
                    onClick={() =>
                      openForm("console", true, consoleConfig, "Console")
                    }
                  />
                </div>
              )}
              {disabledChannels.length > 0 && (
                <div className={styles.channelsGrid}>
                  {disabledChannels.map((channel) => (
                    <ChannelCard
                      key={channel.id}
                      channelKey={channel.type as ChannelKey}
                      displayName={channel.name}
                      config={{
                        ...channel.settings,
                        enabled: false,
                        isBuiltin: isBuiltin(channel.type),
                      }}
                      iconUrl={channelSchemas[channel.type]?.icon}
                      onClick={() => openChannel(channel)}
                    />
                  ))}
                </div>
              )}
              <div className={styles.availableGrid}>
                {orderedTypes
                  .filter((type) => {
                    if (filter === "builtin") return isBuiltin(type);
                    if (filter === "custom") return !isBuiltin(type);
                    return true;
                  })
                  .map((type) => (
                    <ChannelAvailableItem
                      key={type}
                      channelKey={type as ChannelKey}
                      iconUrl={channelSchemas[type]?.icon}
                      onClick={() => openNewChannel(type)}
                    />
                  ))}
              </div>
            </div>
          </>
        )}
      </div>
      <ChannelDrawer
        open={drawerOpen}
        activeKey={activeType}
        activeInstanceId={activeInstanceId}
        activeLabel={activeType ? getChannelLabel(activeType, t) : ""}
        form={form}
        saving={saving}
        deleting={deleting}
        canDelete={Boolean(
          activeConfigured &&
            activeType !== "console" &&
            !primaryHasSecondaries,
        )}
        initialValues={
          activeConfig
            ? { ...activeConfig.settings, enabled: activeConfig.enabled }
            : undefined
        }
        isBuiltin={activeType ? isBuiltin(activeType) : true}
        channelSchema={activeType ? channelSchemas[activeType] : undefined}
        channelDefinition={channelCatalog.find(
          (definition) => definition.key === activeType,
        )}
        onClose={closeDrawer}
        onSubmit={handleSubmit}
        onDelete={handleDelete}
      />
      <AccessControlDrawer
        open={aclDrawerOpen}
        onClose={() => setAclDrawerOpen(false)}
      />
      <PendingApprovalsDrawer
        open={pendingDrawerOpen}
        onClose={() => {
          setPendingDrawerOpen(false);
          fetchPendingCount();
        }}
      />
    </div>
  );
}

export default ChannelsPage;
