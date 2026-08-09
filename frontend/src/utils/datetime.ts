/**
 * 格式化时间为东八区（中国时间）的"年-月-日 时:分:秒"格式
 *
 * 后端以 UTC 时间存储，但 API 返回的字符串可能不带时区标识，
 * 前端 new Date() 会误按本地时区解析，导致时间偏移。
 * 此函数会自动补上 'Z' 后缀确保按 UTC 解析，再转为东八区显示。
 */
export function formatDateTime(dateStr: string): string {
  if (!dateStr) return '-'
  // 检测是否已带时区标识（Z / +08:00 / -0500），未带则补 'Z' 表示 UTC
  let str = dateStr
  if (!/[zZ]$|[+-]\d{2}:?\d{2}$/.test(str)) {
    str += 'Z'
  }
  const d = new Date(str)
  if (isNaN(d.getTime())) return dateStr
  // 按东八区格式化为 YYYY-MM-DD HH:mm:ss
  return d
    .toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
    .replace(/\//g, '-')
}
