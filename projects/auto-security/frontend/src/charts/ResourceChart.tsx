import type { EChartsOption } from 'echarts'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import type { ResourcePoint } from '../types'

export function ResourceChart({ data }: { data: ResourcePoint[] }) {
  const option: EChartsOption = {
    grid: { left: 48, right: 52, top: 36, bottom: 36 },
    tooltip: { trigger: 'axis' },
    legend: { data: ['CPU (%)', '内存 (MB)'], top: 4 },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: data.map((item) => dayjs(item.recorded_at).format('HH:mm:ss')),
      axisLabel: { color: '#8c8c8c' },
    },
    yAxis: [
      {
        type: 'value',
        name: 'CPU %',
        min: 0,
        axisLabel: { formatter: '{value}' },
        splitLine: { lineStyle: { color: '#f0f0f0' } },
      },
      {
        type: 'value',
        name: '内存 MB',
        min: 0,
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: 'CPU (%)',
        type: 'line',
        smooth: true,
        showSymbol: false,
        areaStyle: { opacity: 0.12 },
        data: data.map((item) => item.cpu_usage),
        itemStyle: { color: '#1677ff' },
      },
      {
        name: '内存 (MB)',
        type: 'line',
        smooth: true,
        showSymbol: false,
        yAxisIndex: 1,
        data: data.map((item) => item.memory_usage),
        itemStyle: { color: '#52c41a' },
      },
    ],
  }

  return (
    <ReactECharts
      option={option}
      style={{ height: 300 }}
      notMerge
      lazyUpdate
    />
  )
}
