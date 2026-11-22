export const roles = { reviewer: '业务复核员', analyst: '数据分析员', viewer: '观察员' };
export const sequences = { AB: ['A', 'B'], BA: ['B', 'A'] };
export const states = { queued: '等待计算', ready: '待复核', failed: '运行失败', published: '已发布' };
export const decisions = { retest: '补测后复核', retain: '保留现牌', pilot: '安排局部试挂' };
export const entryKinds = { register: '首次登记', supplement: '补录', modify: '修改', reupload: '重复上传' };
export const entryStates = {
  passed: '通过', missing: '缺测', duplicate: '重复',
  sequence_conflict: '顺序冲突', conflict: '冲突（被覆盖）',
};
export const batchChoices = { original: '保留原始批次', latest_complete: '采用最新完整批次' };
