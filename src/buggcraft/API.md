
## 获取游戏版本列表

http://launchermeta.mojang.com/mc/game/version_manifest.json -> https://bmclapi2.bangbang93.com/mc/game/version_manifest.json

http://launchermeta.mojang.com/mc/game/version_manifest_v2.json -> https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json


```
{
  "latest": {
    "release": "1.21.9",
    "snapshot": "1.21.10-rc1"
  },
  "versions": [
    {
      "id": "1.21.10-rc1",
      "type": "snapshot",
      "url": "https://piston-meta.mojang.com/v1/packages/eb74123b14382225553b0a606bed9762a11c34a1/1.21.10-rc1.json",
      "time": "2025-10-02T12:19:14+00:00",
      "releaseTime": "2025-10-02T12:09:16+00:00"
    },
    {
      "id": "1.21.9",
      "type": "release",
      "url": "https://piston-meta.mojang.com/v1/packages/d7a33415a8e68a8fdff87ab2020e64de021df302/1.21.9.json",
      "time": "2025-10-02T06:44:53+00:00",
      "releaseTime": "2025-09-30T11:58:43+00:00"
    }
  ]
}
```

### 加载器

> https://docs.modrinth.com/api/operations/loaderlist/

GET `https://api.modrinth.com/v2/tag/loader`



## 获取资源数据

> 通过接口获取 模组、资源包、光影包。并附 如何条件查询、搜索等 接口

### 搜索

> 来源 https://docs.modrinth.com/api/operations/searchprojects/

GET `https://api.modrinth.com/v2/search`

**参数**

```
{
    "query": "搜索关键词",
    "facets": [["project_type:mod"]]
}
```

**`facets` 参数说明**

条件查询，`project_type` 支持类型 `mod` `resourcepack` `shader` `modpack` `plugin` `datapack`,


### 项目版本

> 来源 https://docs.modrinth.com/api/operations/getproject/
>
> 来源 https://docs.modrinth.com/api/operations/getprojectversions/

获取版本

GET `https://api.modrinth.com/v2/project/{ID}`

下载地址

GET `https://api.modrinth.com/v2/project/{ID}/version`


### 依赖信息

> 来源 https://docs.modrinth.com/api/operations/getdependencies/

GET `https://api.modrinth.com/v2/project/{id|slug}/dependencies`
