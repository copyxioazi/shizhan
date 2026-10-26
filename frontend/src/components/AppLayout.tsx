import {
  ApartmentOutlined,
  BugOutlined,
  DashboardOutlined,
  FileTextOutlined,
  LogoutOutlined,
  ProjectOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons'
import {
  Avatar,
  Dropdown,
  Layout,
  Menu,
  Space,
  Tag,
  Typography,
  type MenuProps,
} from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/auth'

const { Header, Sider, Content } = Layout

export function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)

  const selectedKey = location.pathname.startsWith('/settings')
    ? '/settings'
    : '/projects'

  const menuItems: MenuProps['items'] = [
    {
      key: '/projects',
      icon: <ProjectOutlined />,
      label: '评估项目',
      onClick: () => navigate('/projects'),
    },
    ...(user?.role === 'admin'
      ? [
          {
            key: '/settings',
            icon: <SettingOutlined />,
            label: '系统配置',
            onClick: () => navigate('/settings'),
          },
        ]
      : []),
  ]

  const dropdownItems: MenuProps['items'] = [
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      onClick: () => {
        logout()
        navigate('/login', { replace: true })
      },
    },
  ]

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={224} theme="dark">
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            padding: '0 20px',
            color: '#fff',
            fontWeight: 600,
            fontSize: 15,
          }}
        >
          <DashboardOutlined style={{ marginRight: 8 }} />
          自动化安全评估
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
        />
        <div
          style={{
            position: 'absolute',
            bottom: 20,
            left: 20,
            right: 20,
            color: 'rgba(255,255,255,0.45)',
            fontSize: 12,
          }}
        >
          <Space size={6}>
            <ApartmentOutlined />
            <BugOutlined />
            <FileTextOutlined />
          </Space>
          <div>v0.1.0 · 需求 v1.3</div>
        </div>
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <Typography.Text strong>自动化安全评估系统</Typography.Text>
          <Dropdown menu={{ items: dropdownItems }} placement="bottomRight">
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size="small" icon={<UserOutlined />} />
              <span>{user?.username}</span>
              <Tag color={user?.role === 'admin' ? 'gold' : 'blue'}>
                {user?.role === 'admin' ? '管理员' : '普通用户'}
              </Tag>
            </Space>
          </Dropdown>
        </Header>
        <Content style={{ margin: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
