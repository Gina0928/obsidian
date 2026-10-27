---
title: "2025|Typora像素级破解教程（新旧版可用）"
source: "https://blog.csdn.net/qq_25828905/article/details/148843115"
author:
  - "[[qq_25828905]]"
published: 2025-06-23
created: 2026-05-14
description: "文章浏览阅读1.4w次，点赞28次，收藏72次。免费激活Typora，_typora"
tags:
  - "clippings"
---
**前言：【注】首先来看看实际情况，Typora的输入序列号，是没有打通的，但是完全不影响Typora的使用，包括"弹窗"可以消除掉，底部"未消除"的提示，然后完全破解进去之后，就完全可以使用了！  
  
如果对"通用"，这里的提示“您的Typora尚未激活”，有什么心理不舒服的话，那就可以不用看这个方法了，如果不介意这个问题，就按照下面的这些方法一步一步往下走，就能破解Typora!**

![[_resources/2025Typora像素级破解教程（新旧版可用）/e9c9448a1d14415e8bccd9429a248042_MD5.png]]

那我们开始破解Typora！

**1、去官网下载Typora： [https://www.typora.net/](https://www.typora.net/ "https://www.typora.net/") [Typora|Typora中文|typora下载|typora 主题](https://www.typora.net/ "Typora|Typora中文|typora下载|typora 主题")**

下载你们想要的版本，如果想要老版本，也可以，新版本，也可以！

![[_resources/2025Typora像素级破解教程（新旧版可用）/2fa9c89c748995592ef6de8b730b5642_MD5.png]] [https://www.typora.net/](https://www.typora.net/ "https://www.typora.net/")

![[_resources/2025Typora像素级破解教程（新旧版可用）/898946d2a1f62cbdc5622168bc4f5871_MD5.png]]

![[_resources/2025Typora像素级破解教程（新旧版可用）/0fdd2ed3106a723722f88bd5e59dbe8a_MD5.png]]

下面这张图，是其他 历史版本 ，你也都可以进行下载！

![[_resources/2025Typora像素级破解教程（新旧版可用）/61f07e783708beaf5631f0e2db84db4a_MD5.png]]

**2、接下来，就是正常安装：** 安装过程，没有什么特殊的地方，正常往下安装就可以，我的直接安装在C盘的，也没有什么问题，因为配的电脑，当时没有分磁盘，就直接安装在C盘了！

**3、安装完成：开始修改文件，处理破解的相关事情！一般如果没有修改安装的地址：**

```swift
C:\Program Files\TyporaSwift
```

**4、根据下面地址，找到文件：LicenseIndex.180dd4c7.4da8909c.chunk.js，右键——打开方式——使用记事本打开，Ctrl+F进行查找：e.hasActivated="true"==e.hasActivated** **替换为：e.hasActivated="true"=="true"，下面是具体路径截图：**

```swift
C:\Program Files\Typora\resources\page-dist\static\js Swift
```

![[_resources/2025Typora像素级破解教程（新旧版可用）/de4a4de6ccc77bc351b2d1f42bcda153_MD5.png]]

![[_resources/2025Typora像素级破解教程（新旧版可用）/7b1fe3d15a67a16c3d73afd71de72e6d_MD5.png]]

![[_resources/2025Typora像素级破解教程（新旧版可用）/725ef182fcb3548672e20eb0b062eba6_MD5.png]]

![[_resources/2025Typora像素级破解教程（新旧版可用）/c14df6e345278bdd3c9568996888d1b4_MD5.png]]

![[_resources/2025Typora像素级破解教程（新旧版可用）/7fc25e07ab12ebdbf79ccf6f68e5f22b_MD5.png]]

![[_resources/2025Typora像素级破解教程（新旧版可用）/7540d23ac24db6924c3002ffbeca75da_MD5.png]]

**5、然后保存，如果没有权限的话，就授权一下权限，这个时候，破解第一步就已经完成了！重新打开软件，发现有个弹窗，提示已经破解成功了！**

但是： **还有两个问题：1、Typora下面，这里还有提示未注册完成的提示！2、Typora每次打开都会提示已经注册完成！提示注册完成界面，已经被我关掉了，就不截图了！**

**6、解决Typora下面，这里还有提示未注册完成的提示的问题！**

![[_resources/2025Typora像素级破解教程（新旧版可用）/62efaa0877f82d0baa4bdc683e40bddc_MD5.png]]

**方案：在Typora的安装路径下面：C:\\Program Files\\Typora\\resources\\locales\\zh-Hans.lproj\\Panel.json打开Panel.json文件，将下面代码2替换掉代码1：**

路径：

```swift
resources\locales\zh-Hans.lproj\Panel.json Swift
```

![[_resources/2025Typora像素级破解教程（新旧版可用）/eb129628ebcce2d18f3ed767b155ff8f_MD5.png]]

![[_resources/2025Typora像素级破解教程（新旧版可用）/91a7fbe8e0687507cf5f50fd6aa90489_MD5.png]]

![[_resources/2025Typora像素级破解教程（新旧版可用）/ef8e8c522cab2bb31330d4855197beab_MD5.png]]

![[_resources/2025Typora像素级破解教程（新旧版可用）/29cbaeb9406d46b0559747251b266524_MD5.png]]

**将代码2替换掉代码1：**

代码1：

```swift
"UNREGISTERED":"未激活"Swift
```

代码2：

```swift
"UNREGISTERED":" "Swift
```

![[_resources/2025Typora像素级破解教程（新旧版可用）/4a00f3829617f55c1fca86c48b762cfa_MD5.png]] ![[_resources/2025Typora像素级破解教程（新旧版可用）/e0f8cbf200b78b73b18650ec6da4bdae_MD5.png]]

**7、此时：未注册完成的提示被消掉！接下来就是消掉，打开Typora提示已经完成注册界面！**

**解决方案：** **同样的逻辑：代码4替换掉代码3**

**地址路径是：**

```swift
C:\Program Files\Typora\resources\page-dist\license.htmlSwift
```

![[_resources/2025Typora像素级破解教程（新旧版可用）/fcda5b04f46e9d8cfada0efd6d2f2ecb_MD5.png]]

![[_resources/2025Typora像素级破解教程（新旧版可用）/e3d327d9c9233ee37e4fbc144bbbc3df_MD5.png]] **代码4替换掉代码3:**

代码3：

```swift
</body></html>Swift
```

代码4：

```swift
</body><script>window.οnlοad=function(){setTimeout(()=>{window.close();},5);}</script></html>Swift
```

**8、【注意】非常重要的点：替换完成之后，先保存，然后用编辑器打开这个文件，用手敲一下：window.onload 根据反馈，应该是代码Bug问题导致的，所以用手重新手敲一下这个代码，之后再次启动，提示注册成功界面，就被关停了！**

![[_resources/2025Typora像素级破解教程（新旧版可用）/ad1b8adad3058b9247ecc2d3299549bc_MD5.png]]

**9、到这里，Typora就能正常使用了，完全破解完成，可以顺滑的打开使用，不受限制！**

**如果有问题，可以参考下面的帖子：**

[图文教程 | 2024Typora最新版免费激活使用教程（新旧版可用）\_typora激活-CSDN博客](https://blog.csdn.net/weixin_73609038/article/details/137751767 "图文教程 | 2024Typora最新版免费激活使用教程（新旧版可用）_typora激活-CSDN博客")