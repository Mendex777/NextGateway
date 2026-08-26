import { useEffect, useMemo, useState } from 'react';
import {
  App as AntApp,
  Button,
  Card,
  ConfigProvider,
  Dropdown,
  Form,
  Input,
  Layout,
  message as messageApi,
  Menu,
  Space,
  Spin,
  Statistic,
  Switch,
  Table,
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

import { api, formatBytes, loadAuth, login, logout, type AuthState, type Node, type Subscription } from './api';
import ScrambleText from './ScrambleText';
import './nextgateway.css';

type Page = 'overview' | 'subscriptions' | 'groups' | 'routing' | 'system';

export default function NextGatewayApp() {
  const [page, setPage] = useState<Page>('subscriptions');
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [actionId, setActionId] = useState('');

  const refresh = async () => {
    setLoading(true);
    setError('');
    try {
      const auth = await loadAuth();
      setAuth(auth);
      if (!auth.authenticated) throw new Error('Требуется вход в NextGateway');
      const [subscriptionRows, nodeRows] = await Promise.all([
        api<Subscription[]>('/subscriptions'),
        api<Node[]>('/nodes'),
      ]);
      setSubscriptions(subscriptionRows);
      setNodes(nodeRows);
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
                      <Button type="primary" icon={<ImportOutlined />}>Добавить источник</Button>
                      <Button type="primary" icon={<MenuOutlined />}>Общие действия</Button>
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
                  />
                </Card>
              </Spin>
            )}
          </Layout.Content>
        </Layout>
      </AntApp>
    </ConfigProvider>
  );
}
