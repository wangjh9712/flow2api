// ==UserScript==
// @name         Flow2API Auto Sync (Auto Refresh)
// @namespace    http://tampermonkey.net/
// @version      1.2
// @description  自动抓取 Google Labs Session Token 并同步，每小时刷新一次页面保活
// @author       Flow2API User
// @match        https://labs.google/*
// @grant        GM_xmlhttpRequest
// @grant        GM_cookie
// @connect      *
// ==/UserScript==

(function() {
    'use strict';

    // ================= 配置区域 =================
    const CONFIG = {
        // Flow2API 服务器地址 (注意结尾不要带斜杠)
        API_BASE_URL: "http://localhost:8000",

        // 填写 setting.toml 中的 api_key
        AUTH_TOKEN: "han1234",

        // 页面刷新间隔 (毫秒)，默认 1 小时 (3600 * 1000)
        // 刷新页面会自动触发一次 Cookie 同步，同时保证 Session 不过期
        RELOAD_INTERVAL: 3600 * 1000
    };
    // ===========================================

    // 发送 ST 到后端服务器
    function sendTokenToServer(st) {
        console.log("[Flow2API Sync] 获取到 Token，准备上传...");

        GM_xmlhttpRequest({
            method: "POST",
            url: `${CONFIG.API_BASE_URL}/api/tokens/sync`,
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${CONFIG.AUTH_TOKEN}`
            },
            data: JSON.stringify({ st: st }),
            onload: function(response) {
                if (response.status === 200) {
                    try {
                        const data = JSON.parse(response.responseText);
                        if (data.success) {
                            console.log(`[Flow2API Sync] ✅ 同步成功! 邮箱: ${data.data.email} (${data.data.action})`);
                        } else {
                            console.error("[Flow2API Sync] ❌ 服务器返回错误:", data);
                        }
                    } catch (e) {
                        console.error("[Flow2API Sync] 解析响应失败:", e);
                    }
                } else {
                    console.error("[Flow2API Sync] ❌ 请求失败 HTTP:", response.status, response.responseText);
                }
            },
            onerror: function(err) {
                console.error("[Flow2API Sync] ❌ 网络错误:", err);
            }
        });
    }

    // 主同步逻辑
    function syncToken() {
        // 使用 GM_cookie API 读取 (支持 HttpOnly)
        GM_cookie.list({ name: '__Secure-next-auth.session-token' }, function(cookies, error) {
            if (error) {
                console.error("[Flow2API Sync] 读取 Cookie 失败:", error);
                return;
            }

            if (cookies && cookies.length > 0) {
                const st = cookies[0].value;
                sendTokenToServer(st);
            } else {
                console.log("[Flow2API Sync] 未找到 Session Token，可能未登录");
            }
        });
    }

    // ================= 执行逻辑 =================

    // 1. 页面加载 3 秒后执行一次同步
    console.log("[Flow2API Sync] 脚本已加载，3秒后执行同步...");
    setTimeout(syncToken, 3000);

    // 2. 设定定时刷新任务 (倒计时)
    const minutes = CONFIG.RELOAD_INTERVAL / 1000 / 60;
    console.log(`[Flow2API Sync] ⏳ 页面将在 ${minutes} 分钟后刷新以更新 Session...`);

    setTimeout(() => {
        console.log("[Flow2API Sync] 🔄 正在刷新页面...");
        window.location.reload();
    }, CONFIG.RELOAD_INTERVAL);

})();