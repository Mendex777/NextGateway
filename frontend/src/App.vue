<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
type EmojiMode = "native" | "off";
type Auth = {
  setup_required: boolean;
  authenticated: boolean;
  username?: string;
  csrf_token?: string;
};
type Node = {
  id: string;
  name: string;
  enabled: boolean;
  protocol: string;
  server: string;
  port: number;
  source: string;
  last_latency_ms?: number;
  last_probe_at?: string;
  last_probe_error?: string;
};
type Group = {
  id: string;
  name: string;
  type: string;
  enabled: boolean;
  node_ids: string[];
};
type Rule = {
  id: string;
  name: string;
  enabled: boolean;
  position: number;
  type: string;
  value?: string;
  target: string;
};
type Subscription = {
  id: string;
  name: string;
  enabled: boolean;
  nodes_count: number;
  update_interval: number;
  last_success?: string;
  last_update?: string;
  last_error?: string;
  remote_name?: string;
  upload_bytes?: number;
  download_bytes?: number;
  total_bytes?: number;
  expires_at?: string;
  announcement?: string;
  support_url?: string;
  web_url?: string;
};
type SubscriptionDetail = Subscription & { nodes: Node[] };
type Health = {
  installed: boolean;
  running: boolean;
  api_available: boolean;
  version?: string;
  error?: string;
};
type DashboardConnection = { hostname: string; port: number; secret: string };
type Operation = { operation_id: string; state: string };
type ConfigStatus = {
  pending_changes: boolean;
  applied_available: boolean;
  error?: string;
};
type Installation = {
  status: string;
  current_step: string;
  desired_config: Record<string, unknown>;
  last_error?: string;
  operation_kind?: string;
  operation_id?: string;
  environment: {
    os: string;
    interfaces: string[];
    addresses: Record<string, string[]>;
    default_gateway?: string;
    default_interface?: string;
  };
};
const auth = ref<Auth>({ setup_required: false, authenticated: false }),
  username = ref(""),
  password = ref(""),
  confirmPassword = ref(""),
  authError = ref("");
const setupToken = new URLSearchParams(window.location.search).get("token");
const hostName = window.location.hostname;
const page = ref("overview"),
  loading = ref(true),
  error = ref("");
const nodes = ref<Node[]>([]),
  groups = ref<Group[]>([]),
  rules = ref<Rule[]>([]),
  subscriptions = ref<Subscription[]>([]),
  health = ref<Health | null>(null);
const dashboardUrl = ref("/dashboard/#/setup");
const installation = ref<Installation | null>(null);
const setupForm = ref({
  interface: "",
  address: "",
  gateway: "",
  dns: "",
  lanSubnet: "",
  coreVersion: "1.19.30",
  installZashboard: true,
});
const setupSubscription = ref({ name: "Primary", url: "" }),
  manualVless = ref(""),
  managerMessage = ref("");
const defaultSubscriptionDeviceProfile = {
  user_agent: "v2raytun/android",
  hwid: "",
  device_os: "Android",
  os_version: "Android 13",
  device_model: "",
  app_version: "2.3.5",
};
let savedSubscriptionDeviceProfile = {};
try {
  savedSubscriptionDeviceProfile = JSON.parse(
    window.localStorage.getItem("nextgateway.subscriptionDeviceProfile") ||
      "{}",
  );
} catch {
  savedSubscriptionDeviceProfile = {};
}
const subscriptionDeviceMode = ref(
  window.localStorage.getItem("nextgateway.subscriptionDeviceMode") === "true",
);
const subscriptionDeviceProfile = ref({
  ...defaultSubscriptionDeviceProfile,
  ...savedSubscriptionDeviceProfile,
});
watch(subscriptionDeviceMode, (enabled) =>
  window.localStorage.setItem(
    "nextgateway.subscriptionDeviceMode",
    String(enabled),
  ),
);
watch(
  subscriptionDeviceProfile,
  (profile) =>
    window.localStorage.setItem(
      "nextgateway.subscriptionDeviceProfile",
      JSON.stringify(profile),
    ),
  { deep: true },
);
const savedEmojiMode = window.localStorage.getItem("nextgateway.emojiMode");
const emojiMode = ref<EmojiMode>(savedEmojiMode === "off" ? "off" : "native");
const newGroup = ref({ name: "", type: "select" }),
  newRule = ref({
    name: "",
    position: 100,
    type: "DOMAIN-SUFFIX",
    value: "",
    target: "VPN-Auto",
  });
const networkOperation = ref<Operation | null>(null);
const editingGroup = ref<Group | null>(null),
  editingRule = ref<Rule | null>(null),
  dirty = ref(false),
  configPreview = ref("");
const configStatus = ref<ConfigStatus | null>(null);
const subscriptionDetails = ref<Record<string, SubscriptionDetail>>({}),
  expandedSubscriptions = ref<string[]>([]),
  probing = ref<string[]>([]),
  probingNodes = ref<string[]>([]),
  probeProgress = ref<Record<string, { done: number; total: number }>>({});
const navigation = [
  ["overview", "Обзор"],
  ["setup", "Настройка"],
  ["dashboard", "Live Dashboard"],
  ["subscriptions", "Подписки и подключения"],
  ["groups", "Группы"],
  ["routing", "Маршрутизация"],
  ["system", "Система"],
];
const enabledNodes = computed(
  () => nodes.value.filter((n) => n.enabled).length,
);
const newManagerUrl = computed(
  () => `http://${setupForm.value.address.split("/")[0]}:8080/`,
);
const managerAddress = computed(() => {
  const env = installation.value?.environment;
  const iface = env?.default_interface || "";
  return env?.addresses[iface]?.[0] || window.location.hostname;
});
const upstreamGateway = computed(
  () => installation.value?.environment.default_gateway || "—",
);
async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  if (auth.value.csrf_token && options.method && options.method !== "GET")
    headers.set("X-CSRF-Token", auth.value.csrf_token);
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ detail: "Ошибка запроса" }));
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
async function loadData() {
  loading.value = true;
  error.value = "";
  try {
    installation.value = await api<Installation>("/setup/state");
    const env = installation.value.environment;
    const iface = env.default_interface || env.interfaces[0] || "";
    const current = env.addresses[iface]?.[0] || "";
    if (!setupForm.value.interface) {
      setupForm.value.interface = iface;
      setupForm.value.address = current;
      setupForm.value.gateway = env.default_gateway || "";
      setupForm.value.dns = env.default_gateway || "";
      setupForm.value.lanSubnet = current
        ? current.replace(/\.\d+\//, ".0/")
        : "";
    }
    const [core, nodeList, groupList, ruleList, subscriptionList] =
      await Promise.all([
        api<Health>("/health/mihomo"),
        api<Node[]>("/nodes"),
        api<Group[]>("/proxy-groups"),
        api<Rule[]>("/routing-rules"),
        api<Subscription[]>("/subscriptions"),
      ]);
    health.value = core;
    nodes.value = nodeList;
    groups.value = groupList;
    rules.value = ruleList;
    subscriptions.value = subscriptionList;
    try {
      const runtimeStatus = await api<ConfigStatus>("/config/mihomo/status");
      configStatus.value = runtimeStatus;
      dirty.value = runtimeStatus.pending_changes;
    } catch (reason) {
      dirty.value = true;
      error.value = `Подключения загружены, но конфигурация Mihomo требует исправления: ${
        reason instanceof Error ? reason.message : "ошибка проверки"
      }`;
    }
    if (core.api_available) {
      const connection = await api<DashboardConnection>(
        "/system/mihomo/dashboard",
      );
      const query = new URLSearchParams({
        hostname: connection.hostname,
        port: String(connection.port),
        secret: connection.secret,
        disableUpgradeCore: "1",
      });
      dashboardUrl.value = `/dashboard/#/setup?${query}`;
    }
  } catch (reason) {
    error.value =
      reason instanceof Error ? reason.message : "Не удалось загрузить данные";
  } finally {
    loading.value = false;
  }
}
async function saveSetupPlan() {
  error.value = "";
  try {
    installation.value = await api<Installation>("/setup/plan", {
      method: "PUT",
      body: JSON.stringify({
        network: {
          interface: setupForm.value.interface,
          address: setupForm.value.address,
          gateway: setupForm.value.gateway,
          dns: setupForm.value.dns
            .split(",")
            .map((v) => v.trim())
            .filter(Boolean),
        },
        gateway: {
          interface: setupForm.value.interface,
          lan_subnet: setupForm.value.lanSubnet,
        },
        core: "mihomo",
        core_version: setupForm.value.coreVersion,
        install_zashboard: setupForm.value.installZashboard,
      }),
    });
  } catch (reason) {
    error.value =
      reason instanceof Error ? reason.message : "План не прошёл проверку";
  }
}
async function runSetupAction(path: string) {
  loading.value = true;
  error.value = "";
  try {
    installation.value = await api<Installation>(path, { method: "POST" });
    if (installation.value.status === "complete") await loadData();
  } catch (reason) {
    error.value =
      reason instanceof Error ? reason.message : "Не удалось выполнить этап";
    try {
      installation.value = await api<Installation>("/setup/state");
    } catch {}
  } finally {
    loading.value = false;
  }
}
async function importSetupSubscription() {
  loading.value = true;
  error.value = "";
  try {
    installation.value = await api<Installation>("/setup/subscription/import", {
      method: "POST",
      body: JSON.stringify(setupSubscription.value),
    });
    setupSubscription.value.url = "";
  } catch (reason) {
    error.value =
      reason instanceof Error
        ? reason.message
        : "Не удалось импортировать подписку";
    throw reason;
  } finally {
    loading.value = false;
  }
}
async function addSubscription() {
  loading.value = true;
  error.value = "";
  try {
    await api<Subscription>("/subscriptions", {
      method: "POST",
      body: JSON.stringify({
        url: setupSubscription.value.url,
        device_profile: subscriptionDeviceMode.value
          ? subscriptionDeviceProfile.value
          : null,
      }),
    });
    setupSubscription.value.url = "";
    await loadData();
    changed("Подписка импортирована. Изменения ещё не применены к Mihomo.");
  } catch (reason) {
    error.value =
      reason instanceof Error
        ? reason.message
        : "Не удалось импортировать подписку";
  } finally {
    loading.value = false;
  }
}
async function addVless() {
  error.value = "";
  const uris = manualVless.value
    .split(/\r?\n/)
    .map((uri) => uri.trim())
    .filter(Boolean);
  if (!uris.length) return;
  const failures: { uri: string; message: string }[] = [];
  let imported = 0;
  for (const uri of uris) {
    try {
      await api<Node>("/nodes/import/vless", {
        method: "POST",
        body: JSON.stringify({ uri }),
      });
      imported += 1;
    } catch (reason) {
      failures.push({
        uri,
        message: reason instanceof Error ? reason.message : "Ошибка импорта",
      });
    }
  }
  if (imported) {
    manualVless.value = failures.map((item) => item.uri).join("\n");
    await loadData();
    changed(
      imported === 1
        ? "VLESS-узел добавлен. Добавьте его в группу и примените конфигурацию Mihomo."
        : `Добавлено VLESS-узлов: ${imported}. Добавьте их в группу и примените конфигурацию Mihomo.`,
    );
  }
  if (failures.length)
    error.value = `Не удалось добавить ${failures.length} из ${uris.length}: ${failures
      .slice(0, 3)
      .map((item) => item.message)
      .join(
        "; ",
      )}${failures.length > 3 ? "; …" : ""}. Ошибочные ссылки оставлены в поле.`;
}
function changed(message: string) {
  dirty.value = true;
  managerMessage.value = message;
}
async function updateNode(node: Node, changes: Partial<Node>) {
  const updated = await api<Node>(`/nodes/${node.id}`, {
    method: "PUT",
    body: JSON.stringify({
      name: changes.name ?? node.name,
      enabled: changes.enabled ?? node.enabled,
    }),
  });
  nodes.value = nodes.value.map((item) =>
    item.id === updated.id ? updated : item,
  );
  for (const detail of Object.values(subscriptionDetails.value))
    detail.nodes = detail.nodes.map((item) =>
      item.id === updated.id ? updated : item,
    );
  changed("Узел изменён. Примените конфигурацию Mihomo.");
}
async function renameNode(node: Node) {
  const name = window.prompt("Новое имя узла", node.name)?.trim();
  if (name && name !== node.name) await updateNode(node, { name });
}
async function removeNode(id: string) {
  if (!window.confirm("Удалить узел? Он также исчезнет из групп.")) return;
  await api<void>(`/nodes/${id}`, { method: "DELETE" });
  await loadData();
  changed("Узел удалён из базы. Примените конфигурацию Mihomo.");
}
async function removeAllManualNodes() {
  const count = nodes.value.filter((node) => node.source === "manual").length;
  if (!count) return;
  if (
    !window.confirm(
      `Удалить все локальные подключения (${count})? Подписки и их подключения затронуты не будут.`,
    )
  )
    return;
  const result = await api<{ deleted: number }>("/nodes/manual/all", {
    method: "DELETE",
  });
  await loadData();
  changed(
    `Удалено локальных подключений: ${result.deleted}. Проверьте группы и примените конфигурацию Mihomo.`,
  );
}
async function updateSubscription(
  sub: Subscription,
  changes: Partial<Subscription>,
) {
  await api<Subscription>(`/subscriptions/${sub.id}`, {
    method: "PUT",
    body: JSON.stringify({
      name: changes.name ?? sub.name,
      enabled: changes.enabled ?? sub.enabled,
      update_interval: (sub as any).update_interval ?? 3600,
    }),
  });
  await loadData();
  changed("Подписка изменена. Примените конфигурацию Mihomo.");
}
async function renameSubscription(sub: Subscription) {
  const name = window.prompt("Новое имя подписки", sub.name)?.trim();
  if (name && name !== sub.name) await updateSubscription(sub, { name });
}
async function refreshSubscription(sub: Subscription) {
  error.value = "";
  try {
    await api<Subscription>(`/subscriptions/${sub.id}/refresh`, {
      method: "POST",
    });
    await loadData();
    managerMessage.value = dirty.value
      ? "Подписка обновлена. Есть проверенные, но ещё не применённые изменения."
      : "Подписка обновлена, конфигурация Mihomo не изменилась.";
  } catch (reason) {
    error.value =
      reason instanceof Error ? reason.message : "Не удалось обновить подписку";
  }
}
async function toggleSubscription(sub: Subscription) {
  if (expandedSubscriptions.value.includes(sub.id)) {
    expandedSubscriptions.value = expandedSubscriptions.value.filter(
      (id) => id !== sub.id,
    );
    return;
  }
  subscriptionDetails.value[sub.id] = await api<SubscriptionDetail>(
    `/subscriptions/${sub.id}`,
  );
  expandedSubscriptions.value.push(sub.id);
}
async function probeSubscription(sub: Subscription) {
  if (probing.value.includes(sub.id)) return;
  if (!subscriptionDetails.value[sub.id])
    subscriptionDetails.value[sub.id] = await api<SubscriptionDetail>(
      `/subscriptions/${sub.id}`,
    );
  if (!expandedSubscriptions.value.includes(sub.id))
    expandedSubscriptions.value.push(sub.id);
  const targetNodes = [...subscriptionDetails.value[sub.id].nodes];
  if (!targetNodes.length) return;
  probing.value.push(sub.id);
  probingNodes.value.push(...targetNodes.map((node) => node.id));
  probeProgress.value[sub.id] = { done: 0, total: targetNodes.length };
  managerMessage.value = `Проверено 0 из ${targetNodes.length} подключений…`;
  let cursor = 0;
  try {
    const worker = async () => {
      while (cursor < targetNodes.length) {
        const node = targetNodes[cursor++];
        try {
          const checked = await api<Node>(`/nodes/${node.id}/probe`, {
            method: "POST",
          });
          subscriptionDetails.value[sub.id].nodes = subscriptionDetails.value[
            sub.id
          ].nodes.map((item) => (item.id === node.id ? checked : item));
        } catch (reason) {
          const message =
            reason instanceof Error ? reason.message : "Ошибка проверки";
          subscriptionDetails.value[sub.id].nodes = subscriptionDetails.value[
            sub.id
          ].nodes.map((item) =>
            item.id === node.id
              ? {
                  ...item,
                  last_latency_ms: undefined,
                  last_probe_error: message,
                }
              : item,
          );
        } finally {
          probingNodes.value = probingNodes.value.filter(
            (id) => id !== node.id,
          );
          probeProgress.value[sub.id].done += 1;
          managerMessage.value = `Проверено ${probeProgress.value[sub.id].done} из ${targetNodes.length} подключений…`;
        }
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(8, targetNodes.length) }, () => worker()),
    );
    managerMessage.value = `Проверка завершена: ${targetNodes.length} подключений.`;
  } finally {
    probing.value = probing.value.filter((id) => id !== sub.id);
    probingNodes.value = probingNodes.value.filter(
      (id) => !targetNodes.some((node) => node.id === id),
    );
    delete probeProgress.value[sub.id];
  }
}
async function probeManualNodes() {
  const probeKey = "manual";
  if (probing.value.includes(probeKey)) return;
  const targetNodes = nodes.value.filter((node) => node.source === "manual");
  if (!targetNodes.length) return;
  probing.value.push(probeKey);
  probingNodes.value.push(...targetNodes.map((node) => node.id));
  probeProgress.value[probeKey] = { done: 0, total: targetNodes.length };
  managerMessage.value = `Проверено 0 из ${targetNodes.length} локальных подключений…`;
  let cursor = 0;
  try {
    const worker = async () => {
      while (cursor < targetNodes.length) {
        const node = targetNodes[cursor++];
        try {
          const checked = await api<Node>(`/nodes/${node.id}/probe`, {
            method: "POST",
          });
          nodes.value = nodes.value.map((item) =>
            item.id === node.id ? checked : item,
          );
        } catch (reason) {
          const message =
            reason instanceof Error ? reason.message : "Ошибка проверки";
          nodes.value = nodes.value.map((item) =>
            item.id === node.id
              ? {
                  ...item,
                  last_latency_ms: undefined,
                  last_probe_error: message,
                }
              : item,
          );
        } finally {
          probingNodes.value = probingNodes.value.filter(
            (id) => id !== node.id,
          );
          probeProgress.value[probeKey].done += 1;
          managerMessage.value = `Проверено ${probeProgress.value[probeKey].done} из ${targetNodes.length} локальных подключений…`;
        }
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(8, targetNodes.length) }, () => worker()),
    );
    managerMessage.value = `Проверка завершена: ${targetNodes.length} локальных подключений.`;
  } finally {
    probing.value = probing.value.filter((id) => id !== probeKey);
    probingNodes.value = probingNodes.value.filter(
      (id) => !targetNodes.some((node) => node.id === id),
    );
    delete probeProgress.value[probeKey];
  }
}
async function probeSingleNode(node: Node, subId?: string) {
  const checked = await api<Node>(`/nodes/${node.id}/probe`, {
    method: "POST",
  });
  if (subId && subscriptionDetails.value[subId])
    subscriptionDetails.value[subId].nodes = subscriptionDetails.value[
      subId
    ].nodes.map((item) => (item.id === node.id ? checked : item));
  managerMessage.value = checked.last_latency_ms
    ? `Узел доступен: ${checked.last_latency_ms} мс`
    : `Узел недоступен: ${checked.last_probe_error || "тайм-аут"}`;
}
async function copyText(value: string) {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const area = document.createElement("textarea");
    area.value = value;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}
async function shareNode(node: Node) {
  const shared = await api<{ uri: string }>(`/nodes/${node.id}/share`);
  await copyText(shared.uri);
  managerMessage.value = `Ссылка ${displayNodeName(node)} скопирована в буфер обмена.`;
}
async function shareSubscription(sub: Subscription) {
  const shared = await api<{ url: string }>(`/subscriptions/${sub.id}/share`);
  await copyText(shared.url);
  managerMessage.value = "Ссылка подписки скопирована в буфер обмена.";
}
function displayNodeName(node: Node) {
  if (emojiMode.value !== "off")
    return node.name.replace(/^[\u{1F1E6}-\u{1F1FF}]{2}\s*/u, "");
  return (
    node.name
      .replace(/\p{Extended_Pictographic}(?:\uFE0F|\uFE0E)?/gu, "")
      .replace(/[\u200D\uFE0E\uFE0F]/g, "")
      .replace(/\s{2,}/g, " ")
      .trim() || "Без названия"
  );
}
function nodeFlag(node: Node) {
  if (emojiMode.value === "off") return "";
  return node.name.match(/^[\u{1F1E6}-\u{1F1FF}]{2}/u)?.[0] || "";
}
function flagAsset(node: Node) {
  const flag = nodeFlag(node);
  if (!flag) return "";
  const codepoints = Array.from(flag, (symbol) =>
    symbol.codePointAt(0)!.toString(16),
  ).join("-");
  return `/emoji-flags/${codepoints}.svg`;
}
function saveEmojiMode() {
  window.localStorage.setItem("nextgateway.emojiMode", emojiMode.value);
  managerMessage.value =
    "Настройка отображения эмодзи сохранена для этого браузера.";
}
async function changeAutoUpdate(sub: Subscription) {
  const minutes = Number(
    window.prompt(
      "Интервал автообновления в минутах (минимум 1)",
      String(Math.round(sub.update_interval / 60)),
    ),
  );
  if (!Number.isFinite(minutes) || minutes < 1) return;
  await api<Subscription>(`/subscriptions/${sub.id}`, {
    method: "PUT",
    body: JSON.stringify({
      name: sub.name,
      enabled: sub.enabled,
      update_interval: Math.round(minutes * 60),
    }),
  });
  await loadData();
  managerMessage.value = "Интервал автообновления сохранён.";
}
function formatBytes(value?: number | null) {
  if (value == null) return "не предоставлено";
  if (value === 0) return "0 Б";
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  const index = Math.min(
    Math.floor(Math.log(value) / Math.log(1024)),
    units.length - 1,
  );
  return `${(value / 1024 ** index).toFixed(index > 2 ? 2 : 1)} ${units[index]}`;
}
function trafficPercent(sub: Subscription) {
  const used = (sub.upload_bytes || 0) + (sub.download_bytes || 0);
  return sub.total_bytes ? Math.min(100, (used / sub.total_bytes) * 100) : 0;
}
function formatDate(value?: string) {
  return value ? new Date(value).toLocaleString("ru-RU") : "никогда";
}
function latency(node: Node) {
  if (node.last_latency_ms) return `${node.last_latency_ms} мс`;
  if (node.last_probe_error) return node.last_probe_error;
  return "не проверен";
}
async function removeSubscription(id: string) {
  if (
    !window.confirm(
      "Удалить подписку и узлы, которые больше нигде не используются?",
    )
  )
    return;
  await api<void>(`/subscriptions/${id}`, { method: "DELETE" });
  await loadData();
  changed("Подписка удалена. Примените конфигурацию Mihomo.");
}
async function addGroup() {
  await api<Group>("/proxy-groups", {
    method: "POST",
    body: JSON.stringify({
      ...newGroup.value,
      node_ids: nodes.value.filter((n) => n.enabled).map((n) => n.id),
    }),
  });
  newGroup.value.name = "";
  await loadData();
  changed("Группа создана. Примените конфигурацию Mihomo.");
}
async function removeGroup(id: string) {
  if (!window.confirm("Удалить прокси-группу?")) return;
  await api<void>(`/proxy-groups/${id}`, { method: "DELETE" });
  await loadData();
  changed("Группа удалена. Примените конфигурацию Mihomo.");
}
async function includeAllNodes(group: Group) {
  await api<Group>(`/proxy-groups/${group.id}`, {
    method: "PUT",
    body: JSON.stringify({
      ...group,
      node_ids: nodes.value.filter((n) => n.enabled).map((n) => n.id),
    }),
  });
  await loadData();
  changed("Состав группы обновлён. Примените конфигурацию Mihomo.");
}
function editGroup(group: Group) {
  editingGroup.value = { ...group, node_ids: [...group.node_ids] };
}
async function saveGroup() {
  if (!editingGroup.value) return;
  await api<Group>(`/proxy-groups/${editingGroup.value.id}`, {
    method: "PUT",
    body: JSON.stringify(editingGroup.value),
  });
  editingGroup.value = null;
  await loadData();
  changed("Группа и её точный состав сохранены. Примените Mihomo.");
}
async function addRule() {
  const payload = {
    ...newRule.value,
    value: newRule.value.type === "MATCH" ? null : newRule.value.value,
  };
  await api<Rule>("/routing-rules", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  newRule.value.name = "";
  await loadData();
  changed("Правило создано. Примените конфигурацию Mihomo.");
}
async function removeRule(id: string) {
  if (!window.confirm("Удалить правило маршрутизации?")) return;
  await api<void>(`/routing-rules/${id}`, { method: "DELETE" });
  await loadData();
  changed("Правило удалено. Примените конфигурацию Mihomo.");
}
function editRule(rule: Rule) {
  editingRule.value = { ...rule };
}
async function saveRule() {
  if (!editingRule.value) return;
  const rule = editingRule.value;
  await api<Rule>(`/routing-rules/${rule.id}`, {
    method: "PUT",
    body: JSON.stringify({
      ...rule,
      value: rule.type === "MATCH" ? null : rule.value,
    }),
  });
  editingRule.value = null;
  await loadData();
  changed("Правило сохранено. Примените Mihomo.");
}
async function moveRule(rule: Rule, offset: number) {
  const ordered = rules.value.map((r) => r.id);
  const from = ordered.indexOf(rule.id),
    to = from + offset;
  if (to < 0 || to >= ordered.length) return;
  [ordered[from], ordered[to]] = [ordered[to], ordered[from]];
  rules.value = await api<Rule[]>("/routing-rules/reorder", {
    method: "POST",
    body: JSON.stringify({ rule_ids: ordered }),
  });
  changed("Порядок правил изменён. Примените Mihomo.");
}
async function showPreview() {
  const preview = await api<{ yaml: string }>("/config/mihomo/preview", {
    method: "POST",
  });
  configPreview.value = preview.yaml;
}
async function applyRuntime() {
  error.value = "";
  try {
    const preview = await api<{ yaml: string }>("/config/mihomo/preview", {
      method: "POST",
    });
    const operation = await api<Operation>("/system/mihomo/config/apply", {
      method: "POST",
      body: JSON.stringify({ yaml: preview.yaml, rollback_timeout: 120 }),
    });
    await api<Operation>(
      `/system/mihomo/config/${operation.operation_id}/confirm`,
      { method: "POST" },
    );
    dirty.value = false;
    configPreview.value = "";
    managerMessage.value =
      "Конфигурация Mihomo проверена, применена и подтверждена.";
    await loadData();
  } catch (reason) {
    error.value =
      reason instanceof Error
        ? reason.message
        : "Не удалось применить конфигурацию";
  }
}
async function applyNetwork() {
  error.value = "";
  try {
    const config = {
      interface: setupForm.value.interface,
      address: setupForm.value.address,
      gateway: setupForm.value.gateway,
      dns: setupForm.value.dns
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean),
      rollback_timeout: 90,
    };
    await api("/system/network/preview", {
      method: "POST",
      body: JSON.stringify(config),
    });
    networkOperation.value = await api<Operation>("/system/network/apply", {
      method: "POST",
      body: JSON.stringify(config),
    });
    managerMessage.value =
      "Сеть применена с таймером отката. Подтвердите её после открытия панели по новому адресу.";
  } catch (reason) {
    error.value =
      reason instanceof Error ? reason.message : "Не удалось применить сеть";
  }
}
async function confirmNetwork() {
  if (!networkOperation.value) return;
  await api<Operation>(
    `/system/network/${networkOperation.value.operation_id}/confirm`,
    { method: "POST" },
  );
  networkOperation.value = null;
  managerMessage.value = "Новая сеть подтверждена.";
  await loadData();
}
async function reopenSetup() {
  installation.value = await api<Installation>("/setup/reopen", {
    method: "POST",
  });
  managerMessage.value =
    "Мастер открыт заново. Его можно покинуть и продолжить позже.";
}
async function authenticate(mode: "setup" | "login") {
  authError.value = "";
  if (mode === "setup" && password.value !== confirmPassword.value) {
    authError.value = "Пароли не совпадают";
    return;
  }
  try {
    auth.value = await api<Auth>(`/auth/${mode}`, {
      method: "POST",
      body: JSON.stringify({
        username: username.value,
        password: password.value,
        setup_token: mode === "setup" ? setupToken : null,
      }),
    });
    password.value = "";
    confirmPassword.value = "";
    if (window.location.search)
      history.replaceState({}, "", window.location.pathname);
    await loadData();
  } catch (reason) {
    authError.value = reason instanceof Error ? reason.message : "Ошибка входа";
  }
}
async function logout() {
  await api<void>("/auth/logout", { method: "POST" });
  auth.value = { setup_required: false, authenticated: false };
}
function showUnhandled(event: PromiseRejectionEvent) {
  error.value =
    event.reason instanceof Error
      ? event.reason.message
      : "Действие не выполнено";
  managerMessage.value = "";
  event.preventDefault();
}
onMounted(async () => {
  window.addEventListener("unhandledrejection", showUnhandled);
  try {
    auth.value = await api<Auth>("/auth/status");
    if (auth.value.authenticated) await loadData();
  } catch (reason) {
    authError.value =
      reason instanceof Error ? reason.message : "Сервис недоступен";
  } finally {
    loading.value = false;
  }
});
</script>
<template>
  <main v-if="!auth.authenticated" class="auth-page">
    <section class="auth-card">
      <div class="brand-mark">NG</div>
      <p class="eyebrow">NextGateway</p>
      <h1>{{ auth.setup_required ? "Первичная настройка" : "Вход в шлюз" }}</h1>
      <p class="muted">Локальная панель управления VPN-шлюзом</p>
      <form
        @submit.prevent="authenticate(auth.setup_required ? 'setup' : 'login')"
      >
        <label
          >Имя пользователя<input
            v-model="username"
            required
            minlength="3"
            autocomplete="username" /></label
        ><label
          >Пароль<input
            v-model="password"
            required
            minlength="12"
            type="password"
            :autocomplete="
              auth.setup_required ? 'new-password' : 'current-password'
            " /></label
        ><label v-if="auth.setup_required"
          >Повторите пароль<input
            v-model="confirmPassword"
            required
            minlength="12"
            type="password"
            autocomplete="new-password"
        /></label>
        <p v-if="authError" class="form-error">{{ authError }}</p>
        <button class="primary" type="submit">
          {{ auth.setup_required ? "Создать администратора" : "Войти" }}
        </button>
      </form>
    </section>
  </main>
  <main v-else-if="!installation" class="auth-page">
    <p class="muted">Проверка состояния установки…</p>
  </main>
  <main v-else-if="page === 'setup'" class="setup-page">
    <section class="setup-card">
      <button class="refresh setup-back" @click="page = 'overview'">
        ← Вернуться в панель
      </button>
      <p class="eyebrow">NextGateway Setup Wizard</p>
      <h1>Настройка VPN-шлюза</h1>
      <p class="muted">
        {{ installation.environment.os }} · этап:
        {{ installation.current_step }}
      </p>
      <p v-if="error || installation.last_error" class="form-error">
        {{ error || installation.last_error }}
      </p>
      <div v-if="installation.status === 'plan_ready'" class="review">
        <h2>План проверен</h2>
        <p>Первым будет установлен Mihomo. Сеть на этом этапе не изменяется.</p>
        <div class="actions">
          <button
            class="refresh"
            @click="installation.status = 'setup_required'"
          >
            Изменить</button
          ><button
            class="primary"
            :disabled="loading"
            @click="runSetupAction('/setup/core/install')"
          >
            Установить Mihomo
          </button>
        </div>
      </div>
      <div v-else-if="installation.status === 'applying'" class="review">
        <h2>Выполняется этап</h2>
        <p>
          Не закрывайте эту страницу. Текущее действие:
          {{ installation.current_step }}.
        </p>
      </div>
      <div v-else-if="installation.status === 'core_ready'" class="review">
        <h2>Mihomo установлен</h2>
        <p>
          Далее адрес интерфейса изменится. Если страница отключится, откройте
          <a :href="newManagerUrl">{{ newManagerUrl }}</a> и войдите снова. Без
          подтверждения конфигурация автоматически откатится.
        </p>
        <button
          class="primary"
          :disabled="loading"
          @click="runSetupAction('/setup/network/apply')"
        >
          Применить сетевые настройки
        </button>
      </div>
      <div
        v-else-if="installation.status === 'network_pending_confirmation'"
        class="review"
      >
        <h2>Новый адрес доступен</h2>
        <p>
          Вы открыли панель после изменения сети. Подтвердите адрес, чтобы
          отменить автоматический откат.
        </p>
        <button
          class="primary"
          :disabled="loading"
          @click="runSetupAction('/setup/network/confirm')"
        >
          Подтвердить сеть
        </button>
      </div>
      <div v-else-if="installation.status === 'network_ready'" class="review">
        <h2>Сеть подтверждена</h2>
        <p>Теперь можно включить IPv4 forwarding и управляемый NAT для LAN.</p>
        <button
          class="primary"
          :disabled="loading"
          @click="runSetupAction('/setup/gateway/apply')"
        >
          Настроить gateway
        </button>
      </div>
      <div
        v-else-if="installation.status === 'gateway_pending_confirmation'"
        class="review"
      >
        <h2>Gateway включён</h2>
        <p>Forwarding и NAT работают с таймером отката.</p>
        <button
          class="primary"
          :disabled="loading"
          @click="runSetupAction('/setup/gateway/confirm')"
        >
          Подтвердить gateway
        </button>
      </div>
      <div v-else-if="installation.status === 'gateway_ready'" class="review">
        <h2>Добавление подписки</h2>
        <p>
          URL будет сохранён отдельно с правами доступа только для NextGateway и
          не появится в API или журналах.
        </p>
        <form
          class="subscription-form"
          @submit.prevent="importSetupSubscription"
        >
          <label
            >Название<input v-model="setupSubscription.name" required /></label
          ><label
            >HTTPS URL подписки<input
              v-model="setupSubscription.url"
              required
              type="password"
              autocomplete="off" /></label
          ><button class="primary" :disabled="loading" type="submit">
            Импортировать и создать VPN-Auto
          </button>
        </form>
      </div>
      <div
        v-else-if="installation.status === 'subscription_ready'"
        class="review"
      >
        <h2>Подписка импортирована</h2>
        <p>
          Совместимые узлы добавлены, создана группа VPN-Auto. Теперь будет
          включён TUN и LAN DNS с таймером отката.
        </p>
        <button
          class="primary"
          :disabled="loading"
          @click="runSetupAction('/setup/tun/apply')"
        >
          Применить TUN и DNS
        </button>
      </div>
      <div
        v-else-if="installation.status === 'tun_pending_confirmation'"
        class="review"
      >
        <h2>TUN и DNS запущены</h2>
        <p>Подтвердите конфигурацию после проверки доступа в Интернет.</p>
        <button
          class="primary"
          :disabled="loading"
          @click="runSetupAction('/setup/tun/confirm')"
        >
          Подтвердить TUN
        </button>
      </div>
      <div v-else-if="installation.status === 'tun_ready'" class="review">
        <h2>VPN-шлюз работает</h2>
        <p>TUN подтверждён. Осталась проверенная установка Zashboard.</p>
        <button
          class="primary"
          :disabled="loading"
          @click="runSetupAction('/setup/zashboard/install')"
        >
          Установить Zashboard
        </button>
      </div>
      <div v-else-if="installation.status === 'failed'" class="review">
        <h2>Этап не завершён</h2>
        <p>
          Безопасный откат сохранён. Исправьте причину и повторите текущий этап.
        </p>
        <button
          v-if="installation.current_step === 'install_core'"
          class="primary"
          @click="runSetupAction('/setup/core/install')"
        >
          Повторить установку ядра</button
        ><button
          v-else-if="installation.current_step === 'network'"
          class="primary"
          @click="runSetupAction('/setup/network/apply')"
        >
          Повторить настройку сети</button
        ><button
          v-else-if="installation.current_step === 'gateway'"
          class="primary"
          @click="runSetupAction('/setup/gateway/apply')"
        >
          Повторить настройку gateway</button
        ><button
          v-else-if="installation.current_step === 'tun'"
          class="primary"
          @click="runSetupAction('/setup/tun/apply')"
        >
          Повторить настройку TUN</button
        ><button
          v-else-if="installation.current_step === 'zashboard'"
          class="primary"
          @click="runSetupAction('/setup/zashboard/install')"
        >
          Повторить установку Zashboard
        </button>
      </div>
      <div v-else-if="installation.status === 'complete'" class="review">
        <h2>Шлюз настроен</h2>
        <p>
          Для обычных изменений используйте разделы панели. Если нужно повторить
          последовательную настройку, мастер можно открыть заново.
        </p>
        <div class="actions">
          <button class="refresh" @click="page = 'overview'">
            Открыть панель</button
          ><button class="primary" @click="reopenSetup">
            Запустить мастер заново
          </button>
        </div>
      </div>
      <form v-else @submit.prevent="saveSetupPlan">
        <div class="setup-grid">
          <label
            >Сетевой интерфейс<select v-model="setupForm.interface">
              <option
                v-for="item in installation.environment.interfaces"
                :key="item"
              >
                {{ item }}
              </option>
            </select></label
          ><label
            >Статический адрес с маской<input
              v-model="setupForm.address"
              required
              placeholder="192.168.1.84/24" /></label
          ><label
            >Адрес роутера<input
              v-model="setupForm.gateway"
              required
              placeholder="192.168.1.1" /></label
          ><label
            >DNS-серверы<input
              v-model="setupForm.dns"
              required
              placeholder="192.168.1.1, 1.1.1.1" /></label
          ><label
            >Подсеть LAN<input
              v-model="setupForm.lanSubnet"
              required
              placeholder="192.168.1.0/24" /></label
          ><label
            >Ядро<select disabled>
              <option>Mihomo</option>
            </select></label
          ><label
            >Версия Mihomo<input
              v-model="setupForm.coreVersion"
              required /></label
          ><label class="check"
            ><input v-model="setupForm.installZashboard" type="checkbox" />
            Установить Zashboard</label
          >
        </div>
        <button class="primary" type="submit">
          Проверить и сохранить план
        </button>
      </form>
    </section>
  </main>
  <div v-else class="shell">
    <aside>
      <div class="logo"><span>NG</span><strong>NextGateway</strong></div>
      <nav>
        <button
          v-for="item in navigation"
          :key="item[0]"
          :class="{ active: page === item[0] }"
          @click="page = item[0]"
        >
          {{ item[1] }}
        </button>
      </nav>
      <div class="user">
        <span>{{ auth.username }}</span
        ><button @click="logout">Выйти</button>
      </div>
    </aside>
    <main class="content">
      <header>
        <div>
          <p class="eyebrow">NextGateway · {{ managerAddress }}</p>
          <h1>{{ navigation.find((item) => item[0] === page)?.[1] }}</h1>
        </div>
        <div class="header-actions">
          <span v-if="dirty" class="pill warn"
            >есть неприменённые изменения</span
          ><button
            v-if="health?.installed"
            class="refresh"
            @click="showPreview"
          >
            Предпросмотр</button
          ><button
            v-if="health?.installed"
            class="primary"
            @click="applyRuntime"
          >
            Применить Mihomo</button
          ><button class="refresh" @click="loadData">Обновить</button>
        </div>
      </header>
      <p v-if="error" class="alert">{{ error }}</p>
      <p v-if="managerMessage" class="notice toast">{{ managerMessage }}</p>
      <div v-if="configPreview" class="preview-box">
        <div class="panel-title">
          <b>Конфигурация перед применением</b
          ><button class="refresh" @click="configPreview = ''">Закрыть</button>
        </div>
        <textarea readonly :value="configPreview"></textarea>
      </div>
      <p v-if="loading" class="muted">Загрузка…</p>
      <template v-if="page === 'overview' && !loading"
        ><section
          v-if="installation.status !== 'complete'"
          class="panel onboarding"
        >
          <div>
            <span class="pill">Настройка не завершена</span>
            <h2>Продолжите, когда будете готовы</h2>
            <p>
              Панель доступна постоянно. Подписку, сеть и ядро можно настроить
              сейчас или позже.
            </p>
          </div>
          <button class="primary" @click="page = 'setup'">
            Продолжить настройку
          </button>
        </section>
        <section class="stats">
          <article>
            <span>Ядро Mihomo</span
            ><strong :class="health?.running ? 'ok' : 'bad'">{{
              health?.running ? "Работает" : "Остановлено"
            }}</strong
            ><small>{{ health?.version || health?.error }}</small>
          </article>
          <article>
            <span>VPN-узлы</span
            ><strong>{{ enabledNodes }} / {{ nodes.length }}</strong
            ><small>активны</small>
          </article>
          <article>
            <span>Прокси-группы</span><strong>{{ groups.length }}</strong
            ><small
              >{{ groups.filter((g) => g.enabled).length }} включено</small
            >
          </article>
          <article>
            <span>Правила</span><strong>{{ rules.length }}</strong
            ><small>маршрутов</small>
          </article>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div>
              <h2>Состояние шлюза</h2>
              <p>Трафик LAN → TUN → VPN</p>
            </div>
            <span :class="['pill', health?.api_available ? 'ok' : '']">{{
              health?.api_available ? "online" : "не настроен"
            }}</span>
          </div>
          <div class="flow">
            <span
              >LAN<b>{{ setupForm.lanSubnet || "не задана" }}</b></span
            ><i>→</i
            ><span
              >NextGateway<b>{{ managerAddress }}</b></span
            ><i>→</i
            ><span
              >Mihomo TUN<b>{{ groups[0]?.name || "не настроен" }}</b></span
            >
          </div>
        </section></template
      >
      <section v-if="page === 'dashboard'" class="panel dashboard-panel">
        <div class="panel-title">
          <div>
            <h2>Zashboard</h2>
            <p>Официальный runtime-интерфейс Mihomo</p>
          </div>
          <a class="refresh" :href="dashboardUrl" target="_blank"
            >Открыть отдельно</a
          >
        </div>
        <iframe title="Zashboard" :src="dashboardUrl"></iframe>
      </section>
      <section v-if="page === 'subscriptions'" class="connections-page">
        <section class="panel compact-panel">
          <div class="panel-title">
            <div>
              <h2>Добавить источник</h2>
              <p>
                Подписки и прямые подключения добавляются и управляются в одном
                месте
              </p>
            </div>
          </div>
          <form
            class="inline-form subscription-source-form"
            @submit.prevent="addSubscription"
          >
            <label
              >HTTPS URL<input
                v-model="setupSubscription.url"
                required
                type="url"
                autocomplete="off"
                placeholder="https://…" /></label
            ><button class="primary" type="submit">Импортировать</button>
            <label class="device-mode-toggle">
              <input v-model="subscriptionDeviceMode" type="checkbox" />
              Требуются данные устройства (Remnawave)
            </label>
            <div v-if="subscriptionDeviceMode" class="device-profile-fields">
              <label
                >User-Agent<input
                  v-model="subscriptionDeviceProfile.user_agent"
                  required
                  autocomplete="off" /></label
              ><label
                >HWID<input
                  v-model="subscriptionDeviceProfile.hwid"
                  required
                  autocomplete="off"
                  placeholder="Идентификатор зарегистрированного устройства" /></label
              ><label
                >ОС устройства<input
                  v-model="subscriptionDeviceProfile.device_os"
                  required
                  autocomplete="off" /></label
              ><label
                >Версия ОС<input
                  v-model="subscriptionDeviceProfile.os_version"
                  required
                  autocomplete="off" /></label
              ><label
                >Модель устройства<input
                  v-model="subscriptionDeviceProfile.device_model"
                  required
                  autocomplete="off" /></label
              ><label
                >Версия приложения<input
                  v-model="subscriptionDeviceProfile.app_version"
                  required
                  autocomplete="off"
              /></label>
            </div>
          </form>
          <form class="inline-form compact" @submit.prevent="addVless">
            <label
              >Прямое VLESS-подключение<textarea
                v-model="manualVless"
                required
                rows="3"
                placeholder="Одна или несколько VLESS-ссылок — по одной на строку"
                autocomplete="off"
              ></textarea></label
            ><button class="primary" type="submit">Добавить</button>
          </form>
        </section>
        <div v-if="!subscriptions.length && !nodes.length" class="panel empty">
          <strong>Подключений пока нет</strong>
          <p>Добавьте подписку или прямой VLESS URI.</p>
        </div>
        <article
          v-for="sub in subscriptions"
          :key="sub.id"
          class="subscription-card"
        >
          <header class="subscription-head">
            <button
              class="expand"
              :class="{ open: expandedSubscriptions.includes(sub.id) }"
              :aria-label="
                expandedSubscriptions.includes(sub.id)
                  ? 'Свернуть'
                  : 'Развернуть'
              "
              @click="toggleSubscription(sub)"
            >
              <svg viewBox="0 0 24 24"><path d="m8 10 4 4 4-4" /></svg>
            </button>
            <div class="subscription-title">
              <h2>{{ sub.remote_name || sub.name }}</h2>
              <small
                >Обновлено: {{ formatDate(sub.last_success) }} · каждые
                {{ Math.round((sub.update_interval / 3600) * 10) / 10 }}
                ч.</small
              >
            </div>
            <div class="subscription-actions">
              <button
                class="icon-action"
                title="Обновить подписку"
                @click="refreshSubscription(sub)"
              >
                <svg viewBox="0 0 24 24">
                  <path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6" />
                </svg></button
              ><button
                class="icon-action"
                title="Проверить все подключения"
                :disabled="probing.includes(sub.id)"
                @click="probeSubscription(sub)"
              >
                <svg viewBox="0 0 24 24">
                  <path d="M4 15a8 8 0 1 1 16 0M12 15l4-4M6 19h12" />
                </svg>
              </button>
              <span v-if="probeProgress[sub.id]" class="probe-progress">
                {{ probeProgress[sub.id].done }}/{{
                  probeProgress[sub.id].total
                }}
              </span>
              <details class="action-menu">
                <summary title="Действия">•••</summary>
                <div>
                  <button @click="renameSubscription(sub)">Переименовать</button
                  ><button @click="changeAutoUpdate(sub)">Автообновление</button
                  ><button @click="shareSubscription(sub)">
                    Скопировать ссылку подписки</button
                  ><button
                    @click="updateSubscription(sub, { enabled: !sub.enabled })"
                  >
                    {{
                      sub.enabled
                        ? "Остановить автообновление"
                        : "Включить автообновление"
                    }}</button
                  ><a
                    v-if="sub.support_url"
                    :href="sub.support_url"
                    target="_blank"
                    >Поддержка</a
                  ><button
                    class="danger-link"
                    @click="removeSubscription(sub.id)"
                  >
                    Удалить
                  </button>
                </div>
              </details>
            </div>
          </header>
          <div class="subscription-meta">
            <div>
              <span>Трафик</span
              ><b
                >{{
                  formatBytes(
                    (sub.upload_bytes || 0) + (sub.download_bytes || 0),
                  )
                }}
                / {{ sub.total_bytes ? formatBytes(sub.total_bytes) : "∞" }}</b
              >
              <div class="traffic-bar">
                <i :style="{ width: trafficPercent(sub) + '%' }"></i>
              </div>
            </div>
            <div>
              <span>Истекает</span
              ><b>{{
                sub.expires_at ? formatDate(sub.expires_at) : "без ограничения"
              }}</b>
            </div>
            <div>
              <span>Подключения</span><b>{{ sub.nodes_count }}</b>
            </div>
            <span
              :class="sub.last_error ? 'bad' : sub.enabled ? 'ok' : 'muted'"
              >{{
                sub.last_error ||
                (sub.enabled
                  ? "автообновление включено"
                  : "автообновление остановлено")
              }}</span
            >
          </div>
          <p v-if="sub.announcement" class="announcement">
            {{ sub.announcement }}
          </p>
          <div
            v-if="expandedSubscriptions.includes(sub.id)"
            class="subscription-nodes"
          >
            <p v-if="!subscriptionDetails[sub.id]" class="muted">
              Загрузка подключений…
            </p>
            <div
              v-for="node in subscriptionDetails[sub.id]?.nodes || []"
              :key="node.id"
              class="connection-row"
            >
              <div class="node-identity">
                <img
                  v-if="flagAsset(node)"
                  class="emoji-flag"
                  :src="flagAsset(node)"
                  :alt="nodeFlag(node)"
                />
                <div>
                  <b>{{ displayNodeName(node) }}</b
                  ><small
                    >{{ node.protocol.toUpperCase() }} · {{ node.server }}:{{
                      node.port
                    }}</small
                  >
                </div>
              </div>
              <span
                v-if="probingNodes.includes(node.id)"
                class="latency-loading"
                aria-label="Проверка подключения"
                title="Проверка подключения"
              >
                <i class="latency-spinner"></i>
              </span>
              <span
                v-else
                :class="
                  node.last_latency_ms
                    ? 'ok'
                    : node.last_probe_error
                      ? 'bad'
                      : 'muted'
                "
                >{{ latency(node) }}</span
              >
              <div class="row-actions">
                <button
                  class="refresh"
                  :disabled="probingNodes.includes(node.id)"
                  @click="probeSingleNode(node, sub.id)"
                >
                  Проверить</button
                ><button
                  class="refresh share-button"
                  title="Скопировать VLESS-ссылку"
                  @click="shareNode(node)"
                >
                  <svg viewBox="0 0 24 24">
                    <path
                      d="M18 8a3 3 0 1 0-2.8-4M6 15a3 3 0 1 0 0 6M18 14a3 3 0 1 0 0 6M8.7 16.4l6.6 2.2M15.4 6.4 8.6 9.8"
                    /></svg
                  ><span>Поделиться</span></button
                ><button
                  class="refresh"
                  @click="updateNode(node, { enabled: !node.enabled })"
                >
                  {{ node.enabled ? "Выключить" : "Включить" }}</button
                ><button class="refresh" @click="renameNode(node)">Имя</button>
              </div>
            </div>
          </div>
        </article>
        <article
          v-if="nodes.some((node) => node.source === 'manual')"
          class="subscription-card"
        >
          <header class="subscription-head">
            <div class="subscription-title">
              <h2>Локальные подключения</h2>
              <small>Добавлены вручную и не зависят от подписок</small>
            </div>
            <div class="subscription-actions">
              <button
                class="icon-action"
                title="Проверить все подключения"
                :disabled="probing.includes('manual')"
                @click="probeManualNodes"
              >
                <svg viewBox="0 0 24 24">
                  <path d="M4 15a8 8 0 1 1 16 0M12 15l4-4M6 19h12" />
                </svg>
              </button>
              <span v-if="probeProgress.manual" class="probe-progress">
                {{ probeProgress.manual.done }}/{{ probeProgress.manual.total }}
              </span>
              <details class="action-menu">
                <summary title="Действия">•••</summary>
                <div>
                  <button class="danger-link" @click="removeAllManualNodes">
                    Удалить все подключения
                  </button>
                </div>
              </details>
            </div>
          </header>
          <div class="subscription-nodes">
            <div
              v-for="node in nodes.filter((item) => item.source === 'manual')"
              :key="node.id"
              class="connection-row"
            >
              <div class="node-identity">
                <img
                  v-if="flagAsset(node)"
                  class="emoji-flag"
                  :src="flagAsset(node)"
                  :alt="nodeFlag(node)"
                />
                <div>
                  <b>{{ displayNodeName(node) }}</b
                  ><small
                    >{{ node.protocol.toUpperCase() }} · {{ node.server }}:{{
                      node.port
                    }}</small
                  >
                </div>
              </div>
              <span
                v-if="probingNodes.includes(node.id)"
                class="latency-loading"
                aria-label="Проверка подключения"
                title="Проверка подключения"
              >
                <i class="latency-spinner"></i>
              </span>
              <span
                v-else
                :class="
                  node.last_latency_ms
                    ? 'ok'
                    : node.last_probe_error
                      ? 'bad'
                      : 'muted'
                "
                >{{ latency(node) }}</span
              >
              <div class="row-actions">
                <button
                  class="refresh"
                  :disabled="probingNodes.includes(node.id)"
                  @click="probeSingleNode(node)"
                >
                  Проверить</button
                ><button
                  class="refresh share-button"
                  title="Скопировать VLESS-ссылку"
                  @click="shareNode(node)"
                >
                  <svg viewBox="0 0 24 24">
                    <path
                      d="M18 8a3 3 0 1 0-2.8-4M6 15a3 3 0 1 0 0 6M18 14a3 3 0 1 0 0 6M8.7 16.4l6.6 2.2M15.4 6.4 8.6 9.8"
                    /></svg
                  ><span>Поделиться</span></button
                ><button
                  class="refresh"
                  @click="updateNode(node, { enabled: !node.enabled })"
                >
                  {{ node.enabled ? "Выключить" : "Включить" }}</button
                ><button class="refresh" @click="renameNode(node)">Имя</button
                ><button class="danger-link" @click="removeNode(node.id)">
                  Удалить
                </button>
              </div>
            </div>
          </div>
        </article>
      </section>
      <section v-if="page === 'groups'" class="panel">
        <div class="panel-title">
          <div>
            <h2>Прокси-группы</h2>
            <p>Состав и порядок узлов задаются отдельно для каждой группы</p>
          </div>
        </div>
        <form class="inline-form" @submit.prevent="addGroup">
          <label
            >Название<input
              v-model="newGroup.name"
              required
              placeholder="VPN-Reserve" /></label
          ><label
            >Тип<select v-model="newGroup.type">
              <option value="select">select</option>
              <option value="url-test">url-test</option>
              <option value="fallback">fallback</option>
            </select></label
          ><button class="primary" type="submit">Создать группу</button>
        </form>
        <div v-for="group in groups" :key="group.id" class="group-card">
          <div class="card-line">
            <div>
              <b>{{ group.name }}</b
              ><small
                >{{ group.type }} · {{ group.node_ids.length }} узлов ·
                {{ group.enabled ? "включена" : "выключена" }}</small
              >
            </div>
            <div class="row-actions">
              <button class="refresh" @click="editGroup(group)">Изменить</button
              ><button class="refresh" @click="includeAllNodes(group)">
                Все узлы</button
              ><button class="danger-link" @click="removeGroup(group.id)">
                Удалить
              </button>
            </div>
          </div>
          <form
            v-if="editingGroup?.id === group.id"
            class="editor"
            @submit.prevent="saveGroup"
          >
            <label>Название<input v-model="editingGroup.name" required /></label
            ><label
              >Тип<select v-model="editingGroup.type">
                <option value="select">select</option>
                <option value="url-test">url-test</option>
                <option value="fallback">fallback</option>
              </select></label
            ><label class="check"
              ><input v-model="editingGroup.enabled" type="checkbox" />
              Включена</label
            >
            <div class="node-picker">
              <label v-for="node in nodes" :key="node.id"
                ><input
                  v-model="editingGroup.node_ids"
                  type="checkbox"
                  :value="node.id"
                />
                {{ node.name }}</label
              >
            </div>
            <div class="actions">
              <button class="primary" type="submit">Сохранить</button
              ><button
                class="refresh"
                type="button"
                @click="editingGroup = null"
              >
                Отмена
              </button>
            </div>
          </form>
        </div>
      </section>
      <section v-if="page === 'routing'" class="panel">
        <div class="panel-title">
          <div>
            <h2>Правила маршрутизации</h2>
            <p>Применяются сверху вниз; порядок меняется стрелками</p>
          </div>
        </div>
        <form class="rule-form" @submit.prevent="addRule">
          <label>Название<input v-model="newRule.name" required /></label
          ><label
            >Позиция<input
              v-model.number="newRule.position"
              required
              type="number"
              min="0" /></label
          ><label
            >Тип<select v-model="newRule.type">
              <option>DOMAIN</option>
              <option>DOMAIN-SUFFIX</option>
              <option>IP-CIDR</option>
              <option>GEOIP</option>
              <option>GEOSITE</option>
              <option>MATCH</option>
            </select></label
          ><label v-if="newRule.type !== 'MATCH'"
            >Значение<input v-model="newRule.value" required /></label
          ><label
            >Цель<select v-model="newRule.target">
              <option v-for="group in groups" :key="group.id">
                {{ group.name }}
              </option>
              <option>DIRECT</option>
              <option>REJECT</option>
            </select></label
          ><button class="primary" type="submit">Добавить правило</button>
        </form>
        <div v-for="rule in rules" :key="rule.id">
          <div class="rule">
            <span>{{ rule.position }}</span>
            <div>
              <b>{{ rule.name }}</b
              ><small>{{ rule.type }} {{ rule.value || "" }}</small>
            </div>
            <code>{{ rule.target }}</code>
            <div class="row-actions">
              <button class="refresh" @click="moveRule(rule, -1)">↑</button
              ><button class="refresh" @click="moveRule(rule, 1)">↓</button
              ><button class="refresh" @click="editRule(rule)">Изменить</button
              ><button class="danger-link" @click="removeRule(rule.id)">
                Удалить
              </button>
            </div>
          </div>
          <form
            v-if="editingRule?.id === rule.id"
            class="rule-form editor"
            @submit.prevent="saveRule"
          >
            <label>Название<input v-model="editingRule.name" required /></label
            ><label
              >Позиция<input
                v-model.number="editingRule.position"
                required
                type="number" /></label
            ><label
              >Тип<select v-model="editingRule.type">
                <option>DOMAIN</option>
                <option>DOMAIN-SUFFIX</option>
                <option>IP-CIDR</option>
                <option>GEOIP</option>
                <option>GEOSITE</option>
                <option>MATCH</option>
              </select></label
            ><label v-if="editingRule.type !== 'MATCH'"
              >Значение<input v-model="editingRule.value" required /></label
            ><label
              >Цель<select v-model="editingRule.target">
                <option v-for="group in groups" :key="group.id">
                  {{ group.name }}
                </option>
                <option>DIRECT</option>
                <option>REJECT</option>
              </select></label
            ><label class="check"
              ><input v-model="editingRule.enabled" type="checkbox" />
              Включено</label
            ><button class="primary" type="submit">Сохранить</button
            ><button class="refresh" type="button" @click="editingRule = null">
              Отмена
            </button>
          </form>
        </div>
      </section>
      <section v-if="page === 'system'" class="panel">
        <div class="panel-title">
          <div>
            <h2>Сеть и система</h2>
            <p>Изменения сети защищены автоматическим откатом</p>
          </div>
          <span :class="['pill', health?.api_available ? 'ok' : 'bad']">{{
            health?.api_available ? "API доступен" : "API недоступен"
          }}</span>
        </div>
        <form class="settings-form" @submit.prevent="applyNetwork">
          <label
            >Интерфейс<select v-model="setupForm.interface">
              <option
                v-for="item in installation.environment.interfaces"
                :key="item"
              >
                {{ item }}
              </option>
            </select></label
          ><label
            >IP с маской<input v-model="setupForm.address" required /></label
          ><label>Роутер<input v-model="setupForm.gateway" required /></label
          ><label>DNS<input v-model="setupForm.dns" required /></label
          ><button class="primary" type="submit">Применить сеть</button
          ><button
            v-if="networkOperation"
            class="refresh"
            type="button"
            @click="confirmNetwork"
          >
            Подтвердить новую сеть
          </button>
        </form>
        <section class="display-settings">
          <div>
            <h3>Отображение эмодзи</h3>
            <p>
              Настройка действует только в этом браузере и не изменяет названия
              подключений на сервере.
            </p>
          </div>
          <label
            >Стиль<select v-model="emojiMode" @change="saveEmojiMode">
              <option value="native">Системные</option>
              <option value="off">Выключены (флаги системные)</option>
            </select></label
          >
          <strong v-if="emojiMode !== 'off'" class="emoji-preview">
            <img src="/emoji-flags/1f1f3-1f1f1.svg" alt="🇳🇱" />
            <img src="/emoji-flags/1f1e9-1f1ea.svg" alt="🇩🇪" />
            <span>🚀 💎 ⚡ 🛡️</span>
          </strong>
          <strong v-else class="emoji-preview">🇳🇱 🇩🇪</strong>
        </section>
        <dl>
          <dt>Хост</dt>
          <dd>{{ hostName }}</dd>
          <dt>LAN адрес</dt>
          <dd>{{ managerAddress }}</dd>
          <dt>Upstream gateway</dt>
          <dd>{{ upstreamGateway }}</dd>
          <dt>Mihomo</dt>
          <dd>{{ health?.version || "—" }}</dd>
          <dt>Режим</dt>
          <dd>
            {{
              health?.api_available ? "TUN + fake-IP DNS" : "ещё не настроен"
            }}
          </dd>
        </dl>
      </section>
    </main>
  </div>
</template>
<style scoped>
.header-actions,
.row-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.notice {
  padding: 12px 14px;
  border: 1px solid #245345;
  border-radius: 10px;
  color: #72e1b9;
  background: #102921;
}
.onboarding {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
}
.onboarding h2 {
  margin-top: 14px;
}
.onboarding p {
  margin-bottom: 0;
  color: #8fa1b2;
}
.inline-form,
.settings-form {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  align-items: end;
  gap: 14px;
  margin-bottom: 24px;
  padding: 18px;
  border: 1px solid #203545;
  border-radius: 12px;
  background: #09141e;
}
.inline-form label,
.settings-form label {
  display: grid;
  gap: 7px;
  color: #92a5b5;
  font-size: 12px;
}
.inline-form input,
.inline-form select,
.inline-form textarea,
.settings-form input,
.settings-form select,
.rule-form input,
.rule-form select {
  min-width: 0;
  padding: 11px;
  color: white;
  border: 1px solid #314556;
  border-radius: 9px;
  background: #07131d;
}
.inline-form textarea {
  min-height: 72px;
  resize: vertical;
  font: inherit;
  line-height: 1.35;
}
.settings-form {
  grid-template-columns: repeat(4, 1fr);
}
.rule-form {
  display: grid;
  grid-template-columns: 1.2fr 0.6fr 1fr 1.2fr 1fr auto;
  align-items: end;
  gap: 10px;
  margin-bottom: 22px;
}
.rule-form label {
  display: grid;
  gap: 7px;
  color: #92a5b5;
  font-size: 11px;
}
.danger-link {
  padding: 0;
  color: #ff9189;
  border: 0;
  cursor: pointer;
  background: none;
}
.warn {
  color: #ffd479;
  border-color: #725d2b;
}
.preview-box,
.editor {
  margin: 0 0 18px;
  padding: 16px;
  border: 1px solid #314556;
  border-radius: 12px;
  background: #09141e;
}
.preview-box textarea {
  width: 100%;
  min-height: 360px;
  resize: vertical;
  color: #cbd7e2;
  border: 0;
  background: #061019;
  font-family: monospace;
}
.group-card {
  border-bottom: 1px solid #203545;
}
.editor {
  display: grid;
  gap: 14px;
}
.editor label {
  display: grid;
  gap: 7px;
  color: #92a5b5;
  font-size: 12px;
}
.editor input,
.editor select {
  padding: 10px;
  color: white;
  border: 1px solid #314556;
  border-radius: 9px;
  background: #07131d;
}
.node-picker {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
  max-height: 280px;
  overflow: auto;
}
.node-picker label,
.editor .check {
  display: flex;
  align-items: center;
  gap: 8px;
}
.connections-page {
  display: grid;
  gap: 12px;
}
.compact-panel {
  padding: 12px;
}
.compact-panel .panel-title {
  margin-bottom: 10px;
}
.compact-panel .panel-title h2,
.compact-panel .panel-title p {
  margin-block: 0 4px;
}
.compact-panel .inline-form {
  margin-bottom: 8px;
  padding: 9px;
}
.subscription-source-form {
  grid-template-columns: 1fr auto;
}
.device-mode-toggle {
  display: flex !important;
  grid-column: 1 / -1;
  grid-template-columns: none !important;
  align-items: center;
  gap: 8px !important;
  cursor: pointer;
}
.device-mode-toggle input {
  width: auto;
}
.device-profile-fields {
  display: grid;
  grid-column: 1 / -1;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 9px;
}
.compact {
  grid-template-columns: 1fr auto;
  margin-bottom: 0;
}
.subscription-card {
  overflow: visible;
  border: 1px solid #263d51;
  border-radius: 16px;
  background: #0c1924;
}
.subscription-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
}
.expand,
.icon-action,
.action-menu summary {
  display: grid;
  width: 34px;
  height: 34px;
  padding: 0;
  place-items: center;
  color: #b9cad7;
  border: 1px solid #31495d;
  border-radius: 9px;
  cursor: pointer;
  background: #101f2c;
}
.expand svg,
.icon-action svg {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.expand svg {
  transition: transform 0.16s ease;
}
.expand.open svg {
  transform: rotate(180deg);
}
.subscription-title {
  flex: 1;
  min-width: 0;
}
.subscription-title h2 {
  margin: 0 0 4px;
  font-size: 18px;
}
.subscription-title small,
.connection-row small {
  display: block;
  color: #7f93a4;
}
.subscription-title h2,
.connection-row b {
  font-family:
    "Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", Manrope,
    system-ui, sans-serif;
}
.node-identity {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
}
.node-identity > div {
  min-width: 0;
}
.latency-loading {
  display: grid;
  min-width: 56px;
  place-items: center;
}
.latency-spinner {
  display: block;
  width: 17px;
  height: 17px;
  border: 2px solid #365366;
  border-top-color: #61ddb5;
  border-radius: 50%;
  animation: latency-spin 0.7s linear infinite;
}
@keyframes latency-spin {
  to {
    transform: rotate(360deg);
  }
}
.emoji-flag {
  flex: 0 0 30px;
  width: 30px;
  height: 22px;
  object-fit: contain;
}
.display-settings {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) minmax(250px, 0.7fr) auto;
  align-items: end;
  gap: 16px;
  margin: 0 0 20px;
  padding: 14px;
  border: 1px solid #203545;
  border-radius: 12px;
  background: #09141e;
}
.display-settings h3,
.display-settings p {
  margin: 0 0 5px;
}
.display-settings p {
  color: #92a5b5;
  font-size: 12px;
}
.display-settings label {
  display: grid;
  gap: 7px;
  color: #92a5b5;
  font-size: 12px;
}
.display-settings select {
  padding: 10px;
  color: white;
  border: 1px solid #314556;
  border-radius: 9px;
  background: #07131d;
}
.emoji-preview {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 190px;
  font-size: 24px;
  white-space: nowrap;
}
.emoji-preview img {
  width: 28px;
  height: 21px;
}
.subscription-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.probe-progress {
  min-width: 48px;
  color: #61ddb5;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-align: center;
}
.action-menu {
  position: relative;
}
.action-menu summary {
  list-style: none;
}
.action-menu > div {
  position: absolute;
  z-index: 5;
  top: 46px;
  right: 0;
  display: grid;
  min-width: 210px;
  padding: 8px;
  border: 1px solid #31495d;
  border-radius: 12px;
  background: #101b25;
  box-shadow: 0 14px 40px #0009;
}
.action-menu button,
.action-menu a {
  padding: 10px;
  color: #cbd7e2;
  border: 0;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
  background: none;
}
.subscription-meta {
  display: grid;
  grid-template-columns: 2fr 1.4fr 0.7fr auto;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-block: 1px solid #203545;
  background: #09151f;
}
.subscription-meta > div {
  display: grid;
  gap: 4px;
}
.subscription-meta span {
  color: #8094a5;
  font-size: 11px;
}
.traffic-bar {
  width: 100%;
  height: 7px;
  overflow: hidden;
  border: 1px solid #31495d;
  border-radius: 999px;
  background: #071019;
}
.traffic-bar i {
  display: block;
  height: 100%;
  min-width: 2px;
  border-radius: inherit;
  background: linear-gradient(90deg, #45cfa1, #72e1b9);
}
.announcement {
  margin: 0;
  padding: 10px 14px;
  color: #c9d6df;
  white-space: pre-wrap;
  background: #132638;
}
.subscription-nodes {
  display: grid;
}
.connection-row {
  display: grid;
  grid-template-columns: 1fr 90px auto;
  align-items: center;
  gap: 12px;
  padding: 9px 14px;
  border-top: 1px solid #1e3242;
}
.connection-row:first-child {
  border-top: 0;
}
.share-button {
  display: inline-grid;
  padding: 8px;
  place-items: center;
}
.share-button svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.share-button span {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
}
.toast {
  position: fixed;
  z-index: 50;
  right: 22px;
  bottom: 22px;
  max-width: min(460px, calc(100vw - 44px));
  margin: 0;
  box-shadow: 0 14px 40px #0009;
}
.setup-back {
  margin-bottom: 18px;
}
.dashboard-panel {
  padding-bottom: 12px;
}
.dashboard-panel iframe {
  width: 100%;
  height: calc(100vh - 190px);
  min-height: 620px;
  border: 0;
  border-radius: 12px;
  background: #09141e;
}
.dashboard-panel a {
  text-decoration: none;
}
.setup-page {
  min-height: 100vh;
  padding: 42px;
  display: grid;
  place-items: center;
}
.setup-card {
  width: min(880px, 100%);
  padding: 36px;
  border: 1px solid #263747;
  border-radius: 20px;
  background: #0c1924ed;
}
.setup-card form {
  margin-top: 28px;
}
.setup-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin-bottom: 24px;
}
.setup-grid label {
  display: grid;
  gap: 7px;
  color: #aebdcc;
  font-size: 12px;
}
.setup-grid input,
.setup-grid select {
  padding: 12px;
  color: white;
  border: 1px solid #314556;
  border-radius: 9px;
  background: #09141f;
}
.setup-grid .check {
  display: flex;
  align-items: center;
  gap: 9px;
}
.setup-grid .check input {
  width: auto;
}
.review {
  margin-top: 28px;
  padding: 24px;
  border: 1px solid #294334;
  border-radius: 12px;
  background: #102820;
}
.review p {
  color: #9aab9f;
}
.review a {
  color: #61e4b4;
}
.actions {
  display: flex;
  gap: 12px;
  margin-top: 18px;
}
.review .primary {
  padding: 11px 16px;
}
button:disabled {
  opacity: 0.55;
  cursor: wait;
}
.subscription-form {
  display: grid;
  gap: 14px;
  margin-top: 20px;
}
.subscription-form label {
  display: grid;
  gap: 7px;
  color: #aebdcc;
  font-size: 12px;
}
.subscription-form input {
  padding: 12px;
  color: white;
  border: 1px solid #314556;
  border-radius: 9px;
  background: #09141f;
}
@media (max-width: 900px) {
  .inline-form,
  .settings-form,
  .rule-form {
    grid-template-columns: 1fr;
  }
  .device-profile-fields {
    grid-template-columns: 1fr;
  }
  .onboarding {
    align-items: stretch;
    flex-direction: column;
  }
}
@media (max-width: 900px) {
  .subscription-meta {
    grid-template-columns: 1fr 1fr;
  }
  .connection-row {
    grid-template-columns: 1fr;
  }
  .subscription-actions {
    flex-wrap: wrap;
  }
}
@media (max-width: 650px) {
  .setup-page {
    padding: 18px;
  }
  .setup-card {
    padding: 24px;
  }
  .setup-grid {
    grid-template-columns: 1fr;
  }
}
</style>
