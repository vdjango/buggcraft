import os
import psutil
import math


class MemoryRecommender:
    """内存推荐器"""
    
    def __init__(self):
        self.mem = psutil.virtual_memory()
    
    def calculate(self):
        """
        计算推荐内存值
        返回：(推荐内存MB, 推荐理由)
        """
        # 获取内存信息
        total_mb = self.mem.total // (1024 * 1024)
        available_mb = self.mem.available // (1024 * 1024)
        
        # 基础推荐值
        base_rec = self._base_recommendation(total_mb)
        reason = f"基于系统总内存({total_mb}MB)推荐: {base_rec}MB"
        
        # 安全限制
        safe_rec = min(base_rec, available_mb * 0.7)
        if safe_rec < base_rec:
            reason += f", 调整为{safe_rec}MB(不超过可用内存的70%)"
        
        # JVM优化
        jvm_rec = self._jvm_optimized(safe_rec)
        if jvm_rec < safe_rec:
            reason += f", JVM优化调整为{jvm_rec}MB(避免GC停顿)"
        
        # Minecraft适配
        mc_rec = self._minecraft_optimized(jvm_rec)
        if mc_rec != jvm_rec:
            reason += f", Minecraft优化调整为{mc_rec}MB"
        
        # 对齐到512MB
        aligned_rec = math.ceil(mc_rec / 512) * 512
        if aligned_rec != mc_rec:
            reason += f", 对齐到512MB倍数: {aligned_rec}MB"
        
        # 最终范围限制
        min_mem = 1024  # 1GB最小值
        max_mem = min(8192, total_mb * 0.7)  # 最大8GB或总内存70%
        
        final_rec = max(min_mem, min(aligned_rec, max_mem))
        
        if final_rec != aligned_rec:
            reason += f", 最终调整为{final_rec}MB(确保在{min_mem}-{max_mem}MB范围内)"
        
        return final_rec, reason
    
    def _base_recommendation(self, total_mb):
        """基于总内存的基础推荐"""
        if total_mb <= 4096:  # <=4GB
            return min(1024, total_mb * 0.5)  # 保守分配
        elif total_mb <= 8192:  # 8GB
            return min(2048, total_mb * 0.4)
        elif total_mb <= 16384:  # 16GB
            return min(4096, total_mb * 0.3)
        else:  # >16GB
            return min(8192, total_mb * 0.25)  # 大内存系统不超过8GB
    
    def _jvm_optimized(self, memory_mb):
        """JVM优化 - 避免过大内存导致GC停顿"""
        # 经验值：超过6GB可能增加GC停顿时间
        return min(memory_mb, 6144)  # 6GB上限
    
    def _minecraft_optimized(self, memory_mb):
        """Minecraft优化 - 根据版本和模组调整"""
        # 基础因子
        factor = 1.0
        
        # 检测是否为模组版（简化实现）
        if self._is_modded():
            factor = 1.2  # 模组版增加20%内存
        
        # 检测是否为高版本（1.13+）
        if self._is_high_version():
            factor = max(factor, 1.1)  # 高版本增加10%内存
        
        return memory_mb * factor
    
    def _is_modded(self):
        """检测是否为模组版 - 简化实现"""
        # 实际应用中需要检测模组存在
        return False
    
    def _is_high_version(self):
        """检测是否为高版本（1.13+） - 简化实现"""
        # 实际应用中需要检测Minecraft版本
        return True


class AdvancedMemoryRecommender(MemoryRecommender):
    """内存推荐器 - 支持模组检测和性能模式"""
    
    def __init__(self, settings_manager):
        super().__init__()
        self.settings_manager = settings_manager
    
    def _minecraft_optimized(self, memory_mb):
        """Minecraft优化 - 增强版"""
        factor = 1.0
        
        # 模组检测
        print('_is_modded', self._is_modded())
        if self._is_modded():
            factor = 1.2  # 模组版增加20%内存
            
            # 特定整合包优化
            memory_mb = self._modpack_optimization(memory_mb)
        
        # 高版本检测
        print('_is_high_version', self._is_high_version())
        if self._is_high_version():
            factor = max(factor, 1.1)  # 高版本增加10%内存
        
        # 性能模式
        print('_performance_mode', self._performance_mode())
        factor *= self._performance_mode()
        
        return memory_mb * factor
    
    def _is_modded(self):
        """检测是否为模组版"""
        # 检查mods文件夹
        minecraft_dir = self.settings_manager.get_setting("minecraft.directory.enable", "")
        if not minecraft_dir:
            return False
            
        mods_dir = os.path.join(minecraft_dir, "mods")
        return os.path.exists(mods_dir) and any(os.scandir(mods_dir))
    
    def _is_high_version(self):
        """检测是否为高版本（1.13+）"""
        version = self.settings_manager.get_setting("minecraft.version", "1.12.2")
        print('version', version)
        try:
            parts = version.split('.')
            major = int(parts[0])
            minor = int(parts[1])
            return major > 1 or (major == 1 and minor >= 13)
        except:
            return False
    
    def _performance_mode(self):
        """性能模式因子"""
        mode = self.settings_manager.get_setting("performance.mode", "balanced")
        if mode == "high_performance":
            return 1.1
        elif mode == "power_saving":
            return 0.9
        return 1.0
    
    def _modpack_optimization(self, memory_mb):
        """特定整合包优化"""
        modpack = self.settings_manager.get_setting("modpack.name", "").lower()
        if "all the mods" in modpack:
            return max(memory_mb, 6144)  # ATM至少6GB
        elif "rlcraft" in modpack:
            return max(memory_mb, 4096)  # RLCraft至少4GB
        elif "skyfactory" in modpack:
            return max(memory_mb, 4096)  # SkyFactory至少4GB
        return memory_mb


if __name__ == "__main__":
    """计算并设置自动分配的内存值"""
    # 计算推荐内存
    memory_recommender = AdvancedMemoryRecommender()
    recommended_memory, reason = memory_recommender.calculate()
    
    # 在UI中显示推荐理由
    # recommendation_label.setText(f"推荐内存: {recommended_memory//1024}GB ({reason})")
