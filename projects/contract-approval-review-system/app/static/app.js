// 框架占位：任务状态轮询骨架。
window.ContractReview = {
  /**
   * 轮询 /api/tasks/{id}/status，直到 done 或 blocked。
   * 后端状态接口已就位，真实流水线待实现。
   */
  async pollTaskStatus(taskId, onUpdate, intervalMs = 2000) {
    while (true) {
      const response = await fetch(`/api/tasks/${taskId}/status`);
      const payload = await response.json();
      if (onUpdate) onUpdate(payload);
      const data = payload && payload.data;
      if (!data || data.terminal) return data;
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  },
};
