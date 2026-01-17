"""三段式去重器 - URL规范化 → 精确Hash → 相似度"""
import hashlib
import re
import unicodedata
from typing import List, Dict, Set, Tuple, Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from dataclasses import dataclass, field

from app.collectors.base import RawNewsData
from app.utils.logger import get_logger

logger = get_logger(__name__)


# 尝试导入 simhash，如果不可用则用简单的方法
try:
    from simhash import Simhash
    SIMHASH_AVAILABLE = True
except ImportError:
    SIMHASH_AVAILABLE = False
    logger.warning("simhash not available, using fallback similarity method")


@dataclass
class DedupResult:
    """去重结果"""
    kept_items: List[RawNewsData]  # 保留的条目
    removed_count: int  # 被移除的数量
    clusters: List["DedupClusterInfo"] = field(default_factory=list)  # 聚类信息


@dataclass
class DedupClusterInfo:
    """去重聚类信息（用于可解释性）"""
    representative_url: str  # 保留的条目 URL
    member_urls: List[str]  # 被合并的条目 URL
    method: str  # url_exact | hash_match | similarity
    similarity_score: Optional[float] = None


class Deduplicator:
    """
    三段式去重器
    
    Stage 1: URL 规范化去重
    - 去除 utm_*, ref, source, fbclid 等追踪参数
    - 统一末尾 slash
    - 统一大小写
    
    Stage 2: 精确 Hash 去重
    - hash(canonical_url)
    - hash(title_normalized + published_date + source)
    
    Stage 3: 标题相似度去重 (SimHash)
    - 对于标题相似度 > threshold 的条目，保留发布时间较早的
    """
    
    # 要移除的 URL 参数
    TRACKING_PARAMS = {
        'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
        'ref', 'source', 'fbclid', 'gclid', 'msclkid', 'mc_cid', 'mc_eid',
        'affiliate', 'partner', 'tracking', '_ga', 'ncid', 'sr_share'
    }
    
    def __init__(self, similarity_threshold: float = 0.85):
        """
        Args:
            similarity_threshold: 相似度阈值 (0-1)，越高越严格
        """
        self.similarity_threshold = similarity_threshold
    
    def deduplicate(self, items: List[RawNewsData]) -> DedupResult:
        """
        执行三段式去重
        
        Returns:
            DedupResult: 包含保留的条目、移除数量和聚类信息
        """
        if not items:
            return DedupResult(kept_items=[], removed_count=0)
        
        original_count = len(items)
        clusters: List[DedupClusterInfo] = []
        
        # Stage 1: URL 规范化去重
        items, url_clusters = self._url_dedup(items)
        clusters.extend(url_clusters)
        logger.debug(f"After URL dedup: {len(items)} items")
        
        # Stage 2: 精确 Hash 去重
        items, hash_clusters = self._hash_dedup(items)
        clusters.extend(hash_clusters)
        logger.debug(f"After hash dedup: {len(items)} items")
        
        # Stage 3: 相似度去重
        items, sim_clusters = self._similarity_dedup(items)
        clusters.extend(sim_clusters)
        logger.debug(f"After similarity dedup: {len(items)} items")
        
        removed_count = original_count - len(items)
        
        logger.info(
            "Deduplication completed",
            original=original_count,
            kept=len(items),
            removed=removed_count,
            clusters=len(clusters)
        )
        
        return DedupResult(
            kept_items=items,
            removed_count=removed_count,
            clusters=clusters
        )
    
    def _url_dedup(self, items: List[RawNewsData]) -> Tuple[List[RawNewsData], List[DedupClusterInfo]]:
        """Stage 1: URL 规范化去重"""
        seen: Dict[str, RawNewsData] = {}  # canonical_url -> first item
        clusters: List[DedupClusterInfo] = []
        duplicates: Dict[str, List[str]] = {}  # canonical_url -> list of original urls
        
        for item in items:
            canonical = self.canonicalize_url(item.url)
            
            if canonical in seen:
                # 记录重复
                if canonical not in duplicates:
                    duplicates[canonical] = [seen[canonical].url]
                duplicates[canonical].append(item.url)
            else:
                seen[canonical] = item
        
        # 创建聚类信息
        for canonical, urls in duplicates.items():
            clusters.append(DedupClusterInfo(
                representative_url=urls[0],
                member_urls=urls[1:],
                method="url_exact"
            ))
        
        return list(seen.values()), clusters
    
    def _hash_dedup(self, items: List[RawNewsData]) -> Tuple[List[RawNewsData], List[DedupClusterInfo]]:
        """Stage 2: 精确 Hash 去重（标题+日期+来源）"""
        seen: Dict[str, RawNewsData] = {}  # content_hash -> first item
        clusters: List[DedupClusterInfo] = []
        duplicates: Dict[str, List[str]] = {}
        
        for item in items:
            content_hash = self.compute_content_hash(item)
            
            if content_hash in seen:
                if content_hash not in duplicates:
                    duplicates[content_hash] = [seen[content_hash].url]
                duplicates[content_hash].append(item.url)
            else:
                seen[content_hash] = item
        
        for content_hash, urls in duplicates.items():
            clusters.append(DedupClusterInfo(
                representative_url=urls[0],
                member_urls=urls[1:],
                method="hash_match"
            ))
        
        return list(seen.values()), clusters
    
    def _similarity_dedup(self, items: List[RawNewsData]) -> Tuple[List[RawNewsData], List[DedupClusterInfo]]:
        """Stage 3: 标题相似度去重"""
        if len(items) <= 1:
            return items, []
        
        if SIMHASH_AVAILABLE:
            return self._simhash_dedup(items)
        else:
            return self._simple_similarity_dedup(items)
    
    def _simhash_dedup(self, items: List[RawNewsData]) -> Tuple[List[RawNewsData], List[DedupClusterInfo]]:
        """使用 SimHash 进行相似度去重"""
        # 计算每个条目的 SimHash
        hashes: List[Tuple[RawNewsData, Simhash]] = []
        for item in items:
            title_norm = self.normalize_title(item.title)
            if title_norm:
                sh = Simhash(title_norm)
                hashes.append((item, sh))
        
        # 找出相似的条目
        kept: List[RawNewsData] = []
        clusters: List[DedupClusterInfo] = []
        removed: Set[int] = set()
        
        for i, (item_i, hash_i) in enumerate(hashes):
            if i in removed:
                continue
            
            similar_items = [item_i.url]
            
            for j, (item_j, hash_j) in enumerate(hashes[i+1:], start=i+1):
                if j in removed:
                    continue
                
                # SimHash 距离（汉明距离）
                distance = hash_i.distance(hash_j)
                # 转换为相似度 (SimHash 是 64-bit，最大距离 64)
                similarity = 1 - (distance / 64)
                
                if similarity >= self.similarity_threshold:
                    similar_items.append(item_j.url)
                    removed.add(j)
            
            kept.append(item_i)
            
            if len(similar_items) > 1:
                clusters.append(DedupClusterInfo(
                    representative_url=similar_items[0],
                    member_urls=similar_items[1:],
                    method="similarity",
                    similarity_score=self.similarity_threshold
                ))
        
        return kept, clusters
    
    def _simple_similarity_dedup(self, items: List[RawNewsData]) -> Tuple[List[RawNewsData], List[DedupClusterInfo]]:
        """简单的相似度去重（基于 Jaccard 相似度）"""
        kept: List[RawNewsData] = []
        clusters: List[DedupClusterInfo] = []
        removed: Set[int] = set()
        
        # 预处理：分词
        tokenized = [set(self.normalize_title(item.title).split()) for item in items]
        
        for i, item_i in enumerate(items):
            if i in removed:
                continue
            
            similar_items = [item_i.url]
            tokens_i = tokenized[i]
            
            for j, item_j in enumerate(items[i+1:], start=i+1):
                if j in removed:
                    continue
                
                tokens_j = tokenized[j]
                
                # Jaccard 相似度
                if tokens_i and tokens_j:
                    intersection = len(tokens_i & tokens_j)
                    union = len(tokens_i | tokens_j)
                    similarity = intersection / union if union > 0 else 0
                else:
                    similarity = 0
                
                if similarity >= self.similarity_threshold:
                    similar_items.append(item_j.url)
                    removed.add(j)
            
            kept.append(item_i)
            
            if len(similar_items) > 1:
                clusters.append(DedupClusterInfo(
                    representative_url=similar_items[0],
                    member_urls=similar_items[1:],
                    method="similarity",
                    similarity_score=self.similarity_threshold
                ))
        
        return kept, clusters
    
    def canonicalize_url(self, url: str) -> str:
        """
        URL 规范化
        - 去除追踪参数
        - 统一末尾 slash
        - 小写域名
        """
        if not url:
            return ""
        
        try:
            parsed = urlparse(url)
            
            # 过滤查询参数
            if parsed.query:
                params = parse_qs(parsed.query, keep_blank_values=False)
                filtered_params = {
                    k: v for k, v in params.items()
                    if k.lower() not in self.TRACKING_PARAMS
                }
                new_query = urlencode(filtered_params, doseq=True)
            else:
                new_query = ""
            
            # 重建 URL
            canonical = urlunparse((
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path.rstrip('/'),
                parsed.params,
                new_query,
                ""  # 去除 fragment
            ))
            
            return canonical
            
        except Exception as e:
            logger.warning(f"Failed to canonicalize URL: {url}, error: {e}")
            return url
    
    def normalize_title(self, title: str) -> str:
        """
        标题规范化
        - 小写
        - 去除标点
        - 去除多余空格
        - Unicode 规范化
        """
        if not title:
            return ""
        
        # Unicode 规范化
        title = unicodedata.normalize('NFKC', title)
        
        # 小写
        title = title.lower()
        
        # 去除标点（保留字母数字空格）
        title = re.sub(r'[^\w\s]', ' ', title)
        
        # 去除多余空格
        title = ' '.join(title.split())
        
        return title
    
    def compute_content_hash(self, item: RawNewsData) -> str:
        """
        计算内容哈希
        hash(title_normalized + published_date + source)
        """
        title_norm = self.normalize_title(item.title)
        
        # 日期格式化到天
        date_str = ""
        if item.published_at:
            date_str = item.published_at.strftime("%Y-%m-%d")
        
        source = item.source or ""
        
        content = f"{title_norm}|{date_str}|{source}"
        
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
