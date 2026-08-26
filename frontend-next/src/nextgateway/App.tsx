import { useEffect, useMemo, useState } from 'react';
import {
  App as AntApp,
  Button,
  Card,
  Checkbox,
  ConfigProvider,
  Dropdown,
  Form,
  Input,
  InputNumber,
  Layout,
  message as messageApi,
  Menu,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  theme,
  type TableColumnsType,
} from 'antd';
import {
  BarsOutlined,
  DashboardOutlined,
  ImportOutlined,
  MenuOutlined,
  PieChartOutlined,
  ReloadOutlined,
  LoginOutlined,
  LogoutOutlined,
  MoreOutlined,
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  SettingOutlined,
  SwapOutlined,
  TagsOutlined,
  ToolOutlined,
} from '@ant-design/icons';

import { api, formatBytes, loadAuth, login, logout, type AuthState, type Node, type ProxyGroup, type RoutingRule, type Subscription, type SubscriptionDetail } from './api';
import ScrambleText from './ScrambleText';
import './nextgateway.css';

type Page = 'overview' | 'subscriptions' | 'groups' | 'routing' | 'system';
type ConfigStatus = { pending_changes: boolean; applied_available: boolean; error?: string };

export default function NextGatewayApp() {
  const [page, setPage] = useState<Page>('subscriptions');
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [actionId, setActionId] = useState('');
  const [sourceOpen, setSourceOpen] = useState(false);
  const [details, setDetails] = useState<Record<string, SubscriptionDetail>>({});
  const [subscriptionForm] = Form.useForm();
  const [vlessForm] = Form.useForm();
  const [deviceMode, setDeviceMode] = useState(false);
  const [configStatus, setConfigStatus] = useState<ConfigStatus | null>(null);
  const [configPreview, setConfigPreview] = useState('');
  const [groups, setGroups] = useState<ProxyGroup[]>([]);
  const [rules, setRules] = useState<RoutingRule[]>([]);
  const [groupEditor, setGroupEditor] = useState<ProxyGroup | 'new' | null>(null);
  const [ruleEditor, setRuleEditor] = useState<RoutingRule | 'new' | null>(null);
  const [groupForm] = Form.useForm();
  const [ruleForm] = Form.useForm();

  const refresh = async () => {
    setLoading(true);
    setError('');
    try {
      const auth = await loadAuth();
      setAuth(auth);
      if (!auth.authenticated) throw new Error('Требуется вход в NextGateway');
      const [subscriptionRows, nodeRows, runtimeStatus, groupRows, ruleRows] = await Promise.all([
        api<Subscription[]>('/subscriptions'),
        api<Node[]>('/nodes'),
        api<ConfigStatus>('/config/mihomo/status'),
        api<ProxyGroup[]>('/proxy-groups'),
        api<RoutingRule[]>('/routing-rules'),
      ]);
      setSubscriptions(subscriptionRows);
      setNodes(nodeRows);
      setConfigStatus(runtimeStatus);
      setGroups(groupRows);
      setRules(ruleRows);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Ошибка загрузки');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const runAction = async (id: string, action: () => Promise<unknown>, success: string) => {
    setActionId(id);
    try {
      await action();
      messageApi.success(success);
      await refresh();
    } catch (reason) {
      messageApi.error(reason instanceof Error ? reason.message : 'Операция не выполнена');
    } finally {
      setActionId('');
    }
  };

  const loadSubscription = async (row: Subscription) => {
    if (details[row.id]) return;
    setActionId(`detail-${row.id}`);
    try {
      const detail = await api<SubscriptionDetail>(`/subscriptions/${row.id}`);
      setDetails((current) => ({ ...current, [row.id]: detail }));
    } catch (reason) {
      messageApi.error(reason instanceof Error ? reason.message : 'Не удалось загрузить подключения');
    } finally {
      setActionId('');
    }
  };

  const importSubscription = async (values: Record<string, string>) => {
    await runAction('add-subscription', async () => {
      const device_profile = deviceMode ? {
        user_agent: values.user_agent,
        hwid: values.hwid,
        device_os: values.device_os,
        os_version: values.os_version,
        device_model: values.device_model,
        app_version: values.app_version,
      } : null;
      await api('/subscriptions', { method: 'POST', body: JSON.stringify({ url: values.url, device_profile }) });
      subscriptionForm.resetFields();
      setSourceOpen(false);
    }, 'Подписка импортирована');
  };

  const importVless = async ({ uris }: { uris: string }) => {
    const links = uris.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
    setActionId('add-vless');
    const failures: string[] = [];
    let imported = 0;
    for (const uri of links) {
      try {
        await api('/nodes/import/vless', { method: 'POST', body: JSON.stringify({ uri }) });
        imported += 1;
      } catch {
        failures.push(uri);
      }
    }
    vlessForm.setFieldValue('uris', failures.join('\n'));
    await refresh();
    setActionId('');
    if (imported) messageApi.success(`Добавлено подключений: ${imported}`);
    if (failures.length) messageApi.warning(`Не удалось добавить: ${failures.length}. Ссылки оставлены в поле.`);
    if (!failures.length) setSourceOpen(false);
  };

  const nodeRows = (items: Node[]) => (
    <Table<Node>
      className="nodes-table"
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={items}
      columns={[
        { title: 'Подключение', render: (_value, node) => <div className="subscription-name"><strong>{node.name}</strong><small>{node.protocol.toUpperCase()} · {node.server}:{node.port}</small></div> },
        { title: 'Задержка', width: 110, align: 'center', render: (_value, node) => actionId === `node-${node.id}` ? <Spin size="small" /> : <Tag color={node.last_latency_ms ? 'green' : node.last_probe_error ? 'red' : 'default'}>{node.last_latency_ms ? `${node.last_latency_ms} мс` : node.last_probe_error ? 'Ошибка' : '—'}</Tag> },
        { title: 'Действия', width: 220, align: 'right', render: (_value, node) => <Space>
          <Button size="small" loading={actionId === `node-${node.id}`} onClick={() => void runAction(`node-${node.id}`, () => api(`/nodes/${node.id}/probe`, { method: 'POST' }), 'Проверка завершена')}>Проверить</Button>
          <Button size="small" onClick={() => void api<{uri:string}>(`/nodes/${node.id}/share`).then(({ uri }) => navigator.clipboard.writeText(uri)).then(() => messageApi.success('Ссылка подключения скопирована'))}>Копировать</Button>
        </Space> },
      ]}
    />
  );

  const showPreview = async () => {
    setActionId('preview');
    try {
      const preview = await api<{ yaml: string }>('/config/mihomo/preview', { method: 'POST' });
      setConfigPreview(preview.yaml);
    } catch (reason) {
      messageApi.error(reason instanceof Error ? reason.message : 'Не удалось собрать конфигурацию');
    } finally {
      setActionId('');
    }
  };

  const applyMihomo = async () => {
    setActionId('apply');
    try {
      const preview = await api<{ yaml: string }>('/config/mihomo/preview', { method: 'POST' });
      const operation = await api<{ operation_id: string }>('/system/mihomo/config/apply', { method: 'POST', body: JSON.stringify({ yaml: preview.yaml, rollback_timeout: 120 }) });
      await api(`/system/mihomo/config/${operation.operation_id}/confirm`, { method: 'POST' });
      messageApi.success('Конфигурация Mihomo применена и подтверждена');
      await refresh();
    } catch (reason) {
      messageApi.error(reason instanceof Error ? reason.message : 'Не удалось применить Mihomo');
    } finally {
      setActionId('');
    }
  };

  const openGroup = (group: ProxyGroup | 'new') => {
    setGroupEditor(group);
    groupForm.setFieldsValue(group === 'new' ? { name: '', type: 'url-test', enabled: true, node_ids: [], health_url: 'https://www.gstatic.com/generate_204', interval: 300, tolerance: 100 } : group);
  };

  const saveGroup = async (values: Omit<ProxyGroup, 'id'>) => {
    const editing = groupEditor !== 'new' && groupEditor;
    await runAction('save-group', () => api(editing ? `/proxy-groups/${editing.id}` : '/proxy-groups', { method: editing ? 'PUT' : 'POST', body: JSON.stringify(values) }), editing ? 'Группа обновлена' : 'Группа создана');
    setGroupEditor(null);
  };

  const openRule = (rule: RoutingRule | 'new') => {
    setRuleEditor(rule);
    ruleForm.setFieldsValue(rule === 'new' ? { name: '', enabled: true, position: rules.length, type: 'DOMAIN-SUFFIX', target: groups[0]?.name || 'DIRECT' } : rule);
  };

  const saveRule = async (values: Omit<RoutingRule, 'id'>) => {
    const editing = ruleEditor !== 'new' && ruleEditor;
    const payload = { ...values, value: values.type === 'MATCH' ? null : values.value || null };
    await runAction('save-rule', () => api(editing ? `/routing-rules/${editing.id}` : '/routing-rules', { method: editing ? 'PUT' : 'POST', body: JSON.stringify(payload) }), editing ? 'Правило обновлено' : 'Правило создано');
    setRuleEditor(null);
  };

  const moveRule = async (rule: RoutingRule, offset: number) => {
    const ordered = rules.map((item) => item.id);
    const from = ordered.indexOf(rule.id);
    const to = from + offset;
    if (to < 0 || to >= ordered.length) return;
    [ordered[from], ordered[to]] = [ordered[to], ordered[from]];
    await runAction(`move-${rule.id}`, () => api('/routing-rules/reorder', { method: 'POST', body: JSON.stringify({ rule_ids: ordered }) }), 'Порядок правил изменён');
  };

  const groupsPage = (
    <Card className="management-card" title="Прокси-группы" extra={<Space><Tag color="blue">{groups.length}</Tag><Button type="primary" icon={<PlusOutlined />} onClick={() => openGroup('new')}>Создать группу</Button></Space>}>
      <Table<ProxyGroup> rowKey="id" size="small" pagination={false} dataSource={groups} columns={[
        { title: 'Включено', width: 90, align: 'center', render: (_value, group) => <Switch checked={group.enabled} onChange={(enabled) => void runAction(`group-${group.id}`, () => api(`/proxy-groups/${group.id}`, { method: 'PUT', body: JSON.stringify({ ...group, enabled }) }), enabled ? 'Группа включена' : 'Группа выключена')} /> },
        { title: 'Название', dataIndex: 'name', render: (name, group) => <div className="subscription-name"><strong>{name}</strong><small>{group.type}</small></div> },
        { title: 'Узлы', width: 100, align: 'center', render: (_value, group) => <Tag color="green">{group.node_ids.length}</Tag> },
        { title: 'Проверка', render: (_value, group) => group.type === 'select' ? 'Ручной выбор' : <span>{group.interval || 300} сек. · допуск {group.tolerance || 0} мс</span> },
        { title: 'Действия', width: 145, align: 'right', render: (_value, group) => <Space><Button aria-label={`Изменить ${group.name}`} icon={<EditOutlined />} onClick={() => openGroup(group)} /><Popconfirm title="Удалить прокси-группу?" onConfirm={() => void runAction(`delete-${group.id}`, () => api(`/proxy-groups/${group.id}`, { method: 'DELETE' }), 'Группа удалена')}><Button danger aria-label={`Удалить ${group.name}`} icon={<DeleteOutlined />} /></Popconfirm></Space> },
      ]} />
    </Card>
  );

  const routingPage = (
    <Card className="management-card" title="Правила маршрутизации" extra={<Space><Tag color="blue">{rules.length}</Tag><Button type="primary" icon={<PlusOutlined />} onClick={() => openRule('new')}>Добавить правило</Button></Space>}>
      <Table<RoutingRule> rowKey="id" size="small" pagination={false} dataSource={rules} columns={[
        { title: '#', dataIndex: 'position', width: 55, align: 'center' },
        { title: 'Включено', width: 90, align: 'center', render: (_value, rule) => <Switch checked={rule.enabled} onChange={(enabled) => void runAction(`rule-${rule.id}`, () => api(`/routing-rules/${rule.id}`, { method: 'PUT', body: JSON.stringify({ ...rule, enabled, value: rule.type === 'MATCH' ? null : rule.value || null }) }), enabled ? 'Правило включено' : 'Правило выключено')} /> },
        { title: 'Правило', render: (_value, rule) => <div className="subscription-name"><strong>{rule.name}</strong><small>{rule.type}{rule.value ? ` · ${rule.value}` : ''}</small></div> },
        { title: 'Цель', dataIndex: 'target', width: 180, render: (target) => <Tag color={target === 'REJECT' ? 'red' : target === 'DIRECT' ? 'default' : 'purple'}>{target}</Tag> },
        { title: 'Порядок', width: 95, align: 'center', render: (_value, rule, index) => <Space size={2}><Button disabled={!index} size="small" icon={<ArrowUpOutlined />} onClick={() => void moveRule(rule, -1)} /><Button disabled={index === rules.length - 1} size="small" icon={<ArrowDownOutlined />} onClick={() => void moveRule(rule, 1)} /></Space> },
        { title: 'Действия', width: 145, align: 'right', render: (_value, rule) => <Space><Button aria-label={`Изменить ${rule.name}`} icon={<EditOutlined />} onClick={() => openRule(rule)} /><Popconfirm title="Удалить правило?" onConfirm={() => void runAction(`delete-${rule.id}`, () => api(`/routing-rules/${rule.id}`, { method: 'DELETE' }), 'Правило удалено')}><Button danger aria-label={`Удалить ${rule.name}`} icon={<DeleteOutlined />} /></Popconfirm></Space> },
      ]} />
    </Card>
  );

  const traffic = useMemo(
    () =>
      subscriptions.reduce(
        (total, subscription) =>
          total + (subscription.upload_bytes || 0) + (subscription.download_bytes || 0),
        0,
      ),
    [subscriptions],
  );

  const columns: TableColumnsType<Subscription> = [
    { title: 'ID', width: 58, align: 'right', render: (_value, _row, index) => index + 1 },
    {
      title: 'Меню',
      width: 72,
      align: 'center',
      render: (_value, row) => (
        <Space size={0}>
          <Button aria-label={`Обновить ${row.remote_name || row.name}`} loading={actionId === `refresh-${row.id}`} type="text" size="small" icon={<ReloadOutlined />} onClick={() => void runAction(`refresh-${row.id}`, () => api(`/subscriptions/${row.id}/refresh`, { method: 'POST' }), 'Подписка обновлена')} />
          <Dropdown menu={{ items: [
            { key: 'probe', label: 'Проверить подключения' },
            { key: 'copy', label: 'Скопировать ссылку' },
          ], onClick: ({ key }) => {
            if (key === 'probe') void runAction(`probe-${row.id}`, () => api(`/subscriptions/${row.id}/probe`, { method: 'POST' }), 'Проверка завершена');
            if (key === 'copy') void api<{url:string}>(`/subscriptions/${row.id}/share`).then(({ url }) => navigator.clipboard.writeText(url)).then(() => messageApi.success('Ссылка подписки скопирована')).catch((reason) => messageApi.error(String(reason)));
          } }} trigger={['click']}><Button aria-label={`Меню ${row.remote_name || row.name}`} loading={actionId === `probe-${row.id}`} type="text" size="small" icon={<MoreOutlined />} /></Dropdown>
        </Space>
      ),
    },
    {
      title: 'Включено',
      width: 88,
      align: 'center',
      render: (_value, row) => <Switch loading={actionId === `toggle-${row.id}`} checked={row.enabled} onChange={(enabled) => void runAction(`toggle-${row.id}`, () => api(`/subscriptions/${row.id}`, { method: 'PUT', body: JSON.stringify({ name: row.name, enabled, update_interval: row.update_interval }) }), enabled ? 'Подписка включена' : 'Подписка приостановлена')} />,
    },
    {
      title: 'Подписка',
      dataIndex: 'remote_name',
      render: (_value, row) => (
        <div className="subscription-name">
          <strong>{row.remote_name || row.name}</strong>
          <small>Обновление каждые {row.update_interval / 3600} ч.</small>
        </div>
      ),
    },
    {
      title: 'Подключения',
      dataIndex: 'nodes_count',
      width: 130,
      align: 'center',
      render: (value) => <Tag color="green">{value}</Tag>,
    },
    {
      title: 'Трафик',
      width: 165,
      align: 'center',
      render: (_value, row) => (
        <Tag color="purple">
          {formatBytes((row.upload_bytes || 0) + (row.download_bytes || 0))} /{' '}
          {row.total_bytes ? formatBytes(row.total_bytes) : '∞'}
        </Tag>
      ),
    },
    {
      title: 'Истекает',
      width: 135,
      align: 'center',
      render: (_value, row) => <Tag color="purple">{row.expires_at || '∞'}</Tag>,
    },
  ];

  const menu = [
    { key: 'overview', icon: <DashboardOutlined />, label: 'Обзор' },
    { key: 'subscriptions', icon: <ImportOutlined />, label: 'Подписки' },
    { key: 'groups', icon: <TagsOutlined />, label: 'Группы' },
    { key: 'routing', icon: <SwapOutlined />, label: 'Маршрутизация' },
    { key: 'system', icon: <SettingOutlined />, label: 'Система' },
  ];

  if (auth && !auth.authenticated) {
    return (
      <ConfigProvider theme={{ algorithm: theme.darkAlgorithm, token: { colorPrimary: '#1677ff' } }}>
        <AntApp>
          <div className="login-page">
            <Card className="login-card">
              <Typography.Title level={2}><ScrambleText>NextGateway</ScrambleText></Typography.Title>
              <Typography.Paragraph type="secondary">Войдите в панель управления шлюзом</Typography.Paragraph>
              <Form layout="vertical" onFinish={async ({ username, password }) => {
                setLoading(true);
                try { setAuth(await login(username, password)); await refresh(); }
                catch (reason) { messageApi.error(reason instanceof Error ? reason.message : 'Ошибка входа'); }
                finally { setLoading(false); }
              }}>
                <Form.Item label="Пользователь" name="username" rules={[{ required: true }]}><Input autoFocus /></Form.Item>
                <Form.Item label="Пароль" name="password" rules={[{ required: true }]}><Input.Password /></Form.Item>
                <Button block type="primary" htmlType="submit" loading={loading} icon={<LoginOutlined />}>Войти</Button>
              </Form>
            </Card>
          </div>
        </AntApp>
      </ConfigProvider>
    );
  }

  return (
    <ConfigProvider theme={{ algorithm: theme.darkAlgorithm, token: { colorPrimary: '#1677ff' } }}>
      <AntApp>
        <Layout className="nextgateway-app">
          <Layout.Sider width={200} theme="dark" className="nextgateway-sider">
            <div className="nextgateway-brand"><ScrambleText>NextGateway</ScrambleText></div>
            <Menu
              mode="inline"
              theme="dark"
              selectedKeys={[page]}
              items={menu}
              onClick={({ key }) => setPage(key as Page)}
            />
            <div className="nextgateway-version"><ToolOutlined /> development</div>
          </Layout.Sider>
          <Layout.Content className="nextgateway-content">
            {page === 'groups' ? groupsPage : page === 'routing' ? routingPage : page !== 'subscriptions' ? (
              <Card><Statistic title={menu.find((item) => item.key === page)?.label} value="В разработке" /></Card>
            ) : (
              <Spin spinning={loading}>
                {error && auth?.authenticated && <Card><Tag color="red">{error}</Tag></Card>}
                <div className="summary-grid">
                  <Card hoverable><Statistic title="Общий трафик" value={formatBytes(traffic)} prefix={<PieChartOutlined />} /></Card>
                  <Card hoverable><Statistic title="Всего подписок" value={subscriptions.length} prefix={<BarsOutlined />} /></Card>
                  <Card hoverable><Statistic title="Всего подключений" value={nodes.length} prefix={<ImportOutlined />} /></Card>
                </div>
                <Card
                  className="subscriptions-card"
                  title={
                    <Space>
                      <Button type="primary" icon={<ImportOutlined />} onClick={() => setSourceOpen(true)}>Добавить источник</Button>
                      <Dropdown trigger={['click']} menu={{ items: [
                        { key: 'preview', label: 'Предпросмотр конфигурации' },
                        { key: 'apply', label: 'Применить Mihomo', danger: true },
                        { key: 'reload', label: 'Обновить данные' },
                      ], onClick: ({ key }) => {
                        if (key === 'preview') void showPreview();
                        if (key === 'reload') void refresh();
                        if (key === 'apply' && window.confirm('Применить текущую конфигурацию Mihomo? Соединения могут кратковременно переподключиться.')) void applyMihomo();
                      } }}><Button loading={actionId === 'preview' || actionId === 'apply'} type="primary" icon={<MenuOutlined />}>Общие действия</Button></Dropdown>
                      {configStatus?.pending_changes && <Tag color="orange">Есть неприменённые изменения</Tag>}
                      <Button icon={<LogoutOutlined />} onClick={() => void logout().then(() => setAuth({ setup_required: false, authenticated: false }))}>Выйти</Button>
                    </Space>
                  }
                >
                  <Table
                    rowKey="id"
                    size="small"
                    rowSelection={{}}
                    columns={columns}
                    dataSource={subscriptions}
                    pagination={false}
                    scroll={{ x: 900 }}
                    expandable={{
                      onExpand: (expanded, row) => { if (expanded) void loadSubscription(row); },
                      expandedRowRender: (row) => actionId === `detail-${row.id}` ? <Spin /> : nodeRows(details[row.id]?.nodes || []),
                    }}
                  />
                </Card>
                {nodes.some((node) => node.source === 'manual') && <Card className="subscriptions-card" title="Локальные подключения">{nodeRows(nodes.filter((node) => node.source === 'manual'))}</Card>}
              </Spin>
            )}
          </Layout.Content>
        </Layout>
        <Modal open={sourceOpen} onCancel={() => setSourceOpen(false)} footer={null} title="Добавить источник" width={680} destroyOnHidden>
          <Tabs items={[
            { key: 'subscription', label: 'HTTPS URL', children: <Form form={subscriptionForm} layout="vertical" initialValues={{ user_agent: 'v2raytun/android', device_os: 'Android', os_version: 'Android 13', app_version: '2.3.5' }} onFinish={importSubscription}>
              <Form.Item name="url" label="Ссылка на подписку" rules={[{ required: true }, { type: 'url' }]}><Input placeholder="https://…" /></Form.Item>
              <Checkbox checked={deviceMode} onChange={(event) => setDeviceMode(event.target.checked)}>Требуются данные устройства (Remnawave)</Checkbox>
              {deviceMode && <div className="device-grid">
                <Form.Item name="user_agent" label="User-Agent" rules={[{ required: true }]}><Input /></Form.Item>
                <Form.Item name="hwid" label="HWID" rules={[{ required: true }]}><Input /></Form.Item>
                <Form.Item name="device_os" label="ОС устройства" rules={[{ required: true }]}><Input /></Form.Item>
                <Form.Item name="os_version" label="Версия ОС" rules={[{ required: true }]}><Input /></Form.Item>
                <Form.Item name="device_model" label="Модель устройства" rules={[{ required: true }]}><Input /></Form.Item>
                <Form.Item name="app_version" label="Версия приложения" rules={[{ required: true }]}><Input /></Form.Item>
              </div>}
              <Button type="primary" htmlType="submit" loading={actionId === 'add-subscription'}>Импортировать</Button>
            </Form> },
            { key: 'vless', label: 'Прямые VLESS', children: <Form form={vlessForm} layout="vertical" onFinish={importVless}>
              <Form.Item name="uris" label="Одна или несколько ссылок" rules={[{ required: true }]}><Input.TextArea rows={7} placeholder="VLESS-ссылки — по одной на строку" /></Form.Item>
              <Button type="primary" htmlType="submit" loading={actionId === 'add-vless'}>Добавить подключения</Button>
            </Form> },
          ]} />
        </Modal>
        <Modal open={Boolean(configPreview)} onCancel={() => setConfigPreview('')} footer={<Button onClick={() => setConfigPreview('')}>Закрыть</Button>} title="Предпросмотр конфигурации Mihomo" width={900}>
          <Input.TextArea className="config-preview" value={configPreview} readOnly autoSize={{ minRows: 16, maxRows: 28 }} />
        </Modal>
        <Modal open={Boolean(groupEditor)} onCancel={() => setGroupEditor(null)} footer={null} title={groupEditor === 'new' ? 'Создать прокси-группу' : 'Изменить прокси-группу'} width={760} destroyOnHidden>
          <Form form={groupForm} layout="vertical" onFinish={saveGroup}>
            <div className="editor-grid"><Form.Item name="name" label="Название" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="type" label="Тип" rules={[{ required: true }]}><Select options={['select','url-test','fallback'].map((value) => ({ value, label: value }))} /></Form.Item></div>
            <Form.Item name="enabled" valuePropName="checked"><Checkbox>Группа включена</Checkbox></Form.Item>
            <Form.Item name="node_ids" label="Узлы"><Select mode="multiple" showSearch optionFilterProp="label" maxTagCount="responsive" options={nodes.map((node) => ({ value: node.id, label: node.name }))} /></Form.Item>
            <div className="editor-grid"><Form.Item name="health_url" label="URL проверки"><Input /></Form.Item><Form.Item name="interval" label="Интервал, сек."><InputNumber min={10} /></Form.Item><Form.Item name="tolerance" label="Допуск, мс"><InputNumber min={0} /></Form.Item></div>
            <Space><Button type="primary" htmlType="submit" loading={actionId === 'save-group'}>Сохранить</Button><Button onClick={() => setGroupEditor(null)}>Отмена</Button></Space>
          </Form>
        </Modal>
        <Modal open={Boolean(ruleEditor)} onCancel={() => setRuleEditor(null)} footer={null} title={ruleEditor === 'new' ? 'Добавить правило' : 'Изменить правило'} width={760} destroyOnHidden>
          <Form form={ruleForm} layout="vertical" onFinish={saveRule}>
            <div className="editor-grid"><Form.Item name="name" label="Название" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="position" label="Позиция" rules={[{ required: true }]}><InputNumber min={0} /></Form.Item></div>
            <div className="editor-grid"><Form.Item name="type" label="Тип" rules={[{ required: true }]}><Select options={['DOMAIN','DOMAIN-SUFFIX','DOMAIN-KEYWORD','IP-CIDR','IP-CIDR6','SRC-IP-CIDR','DST-PORT','SRC-PORT','NETWORK','RULE-SET','GEOIP','GEOSITE','MATCH'].map((value) => ({ value, label: value }))} /></Form.Item><Form.Item noStyle shouldUpdate={(before, after) => before.type !== after.type}>{({ getFieldValue }) => getFieldValue('type') !== 'MATCH' ? <Form.Item name="value" label="Значение" rules={[{ required: true }]}><Input /></Form.Item> : <span />}</Form.Item></div>
            <Form.Item name="target" label="Цель" rules={[{ required: true }]}><Select showSearch options={[...groups.map((group) => ({ value: group.name, label: group.name })), { value: 'DIRECT', label: 'DIRECT' }, { value: 'REJECT', label: 'REJECT' }]} /></Form.Item>
            <Form.Item name="enabled" valuePropName="checked"><Checkbox>Правило включено</Checkbox></Form.Item>
            <Space><Button type="primary" htmlType="submit" loading={actionId === 'save-rule'}>Сохранить</Button><Button onClick={() => setRuleEditor(null)}>Отмена</Button></Space>
          </Form>
        </Modal>
      </AntApp>
    </ConfigProvider>
  );
}
