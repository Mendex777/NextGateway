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
  Layout,
  message as messageApi,
  Menu,
  Modal,
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
  SettingOutlined,
  SwapOutlined,
  TagsOutlined,
  ToolOutlined,
} from '@ant-design/icons';

import { api, formatBytes, loadAuth, login, logout, type AuthState, type Node, type Subscription, type SubscriptionDetail } from './api';
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

  const refresh = async () => {
    setLoading(true);
    setError('');
    try {
      const auth = await loadAuth();
      setAuth(auth);
      if (!auth.authenticated) throw new Error('Требуется вход в NextGateway');
      const [subscriptionRows, nodeRows, runtimeStatus] = await Promise.all([
        api<Subscription[]>('/subscriptions'),
        api<Node[]>('/nodes'),
        api<ConfigStatus>('/config/mihomo/status'),
      ]);
      setSubscriptions(subscriptionRows);
      setNodes(nodeRows);
      setConfigStatus(runtimeStatus);
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
            {page !== 'subscriptions' ? (
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
      </AntApp>
    </ConfigProvider>
  );
}
