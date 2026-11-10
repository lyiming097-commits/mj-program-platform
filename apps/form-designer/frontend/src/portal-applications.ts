export const portalCategories = ['产品管理', '销售管理', '订单管理', '财务管理', '内部管理', '其他应用'] as const
export type PortalCategory = typeof portalCategories[number]

interface PortalApplication {
  name: string
  description: string
  href?: string
  approvalCenter?: true
}

export const portalApplications: Record<PortalCategory, PortalApplication[]> = {
  产品管理: [
    { name: '开发管理', description: '需求、进度与版本管理' },
    { name: '产品档案', description: '产品资料、参数、证书管理' },
    { name: '竞品调查', description: '竞品情报采集与公司级竞品库', href: '/competitive/release-20260910-search-location/' },
  ],
  销售管理: [{ name: '迈杰服务', description: '售前、售中、售后协同管理', href: '/after-sales/' }],
  订单管理: [{ name: '线缆商城', description: '选购线缆与查看订单', href: '/cable-mall/' }],
  财务管理: [],
  内部管理: [{ name: '审批中心', description: '查看待办、申请和抄送记录', approvalCenter: true }],
  其他应用: [],
}
