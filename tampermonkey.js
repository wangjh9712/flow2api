// ==UserScript==
// @name         Flow2API Auto Sync & Login (Humanized)
// @namespace    http://tampermonkey.net/
// @version      1.5
// @description  自动同步 Token，处理中间登录页，并模拟人工随机延迟输入密码
// @author       Flow2API User
// @match        https://labs.google/*
// @match        https://accounts.google.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_cookie
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_registerMenuCommand
// @connect      *
// ==/UserScript==

(function() {
    'use strict';

    // ================= 配置区域 =================
    const CONFIG = {
        // Flow2API 服务器地址
        API_BASE_URL: "http://localhost:8000",

        // Flow2API 的 API Key
        AUTH_TOKEN: "han1234",

        // [Labs页面] 刷新间隔 (默认 1 小时)
        RELOAD_INTERVAL: 3600 * 1000
    };
    // ===========================================

    // 注册菜单：设置密码
    GM_registerMenuCommand("🔑 设置 Google 自动登录密码", function() {
        const oldPwd = GM_getValue("GOOGLE_PASSWORD", "");
        const newPwd = prompt("请输入用于自动登录的 Google 密码:\n(密码将安全存储在本地)", oldPwd);
        if (newPwd !== null) {
            GM_setValue("GOOGLE_PASSWORD", newPwd);
            alert("✅ 密码已保存！脚本将使用模拟人工打字的方式输入。");
        }
    });

    // 注册菜单：清除密码
    GM_registerMenuCommand("🗑️ 清除已保存的密码", function() {
        if(confirm("确定要清除本地存储的密码吗？")) {
            GM_setValue("GOOGLE_PASSWORD", "");
            alert("已清除。");
        }
    });

    // ================= 路由分发 =================
    const currentHost = window.location.hostname;
    const currentPath = window.location.pathname;

    if (currentHost.includes('labs.google')) {
        // 特殊处理：Auth.js 中间登录页
        if (currentPath.includes('/auth/signin')) {
            handleLabsAuthPage();
        } else {
            handleLabsGoogle();
        }
    } else if (currentHost.includes('accounts.google.com')) {
        handleAccountsGoogle();
    }

    // ================= 场景 1: Labs 中间登录页 =================
    // 页面: https://labs.google/fx/api/auth/signin
    function handleLabsAuthPage() {
        console.log("[Flow2API Login] 检测到 Auth.js 中间登录页...");

        const checkBtn = setInterval(() => {
            // 查找 "Sign in with Google" 按钮
            // 策略1: 这种特定页面的 button[type="submit"]
            // 策略2: 包含 provider-logo 的 form 里的 button
            const btn = document.querySelector('form button[type="submit"]') ||
                        document.querySelector('button.button');

            if (btn) {
                console.log("[Flow2API Login] 发现登录按钮，点击跳转...");
                clearInterval(checkBtn);
                btn.click();
            }
        }, 1000);
    }

    // ================= 场景 2: Google 账号登录页 =================
    // 页面: https://accounts.google.com/*
    function handleAccountsGoogle() {
        console.log("[Flow2API Login] 检测到 Google 登录页面，启动自动登录检测...");
        // 轮询检测页面状态
        setInterval(() => { tryAttemptLogin(); }, 1500);
    }

    // 全局状态锁，防止重复触发输入
    let isTyping = false;

    async function tryAttemptLogin() {
        if (isTyping) return;

        // --- 子场景 A: 账号选择页 ---
        const accountItem = document.querySelector('ul li:first-child div[role="link"]');
        if (accountItem) {
            console.log("[Flow2API Login] 发现账号列表，点击第一个账号...");
            accountItem.click();
            return;
        }

        // --- 子场景 B: 密码输入页 ---
        const passwordInput = document.querySelector('input[name="Passwd"]');
        const nextButton = document.querySelector('#passwordNext');

        if (passwordInput && nextButton) {
            // 只有当密码框可见且为空时才输入
            if (passwordInput.offsetParent !== null && !passwordInput.value) {
                const savedPassword = GM_getValue("GOOGLE_PASSWORD", "");

                if (!savedPassword) {
                    console.warn("[Flow2API Login] ❌ 未检测到密码！请在油猴菜单中设置。");
                    return;
                }

                // 开始模拟输入
                isTyping = true;
                console.log("[Flow2API Login] 准备模拟人工输入密码...");

                // 1. 聚焦输入框
                passwordInput.focus();
                await sleep(500);

                // 2. 一个字一个字打进去
                await typeStringSimulate(passwordInput, savedPassword);

                // 3. 输入完成，等待片刻
                console.log("[Flow2API Login] 输入完成，等待点击...");
                await sleep(800 + Math.random() * 500);

                // 4. 点击下一步
                const btn = nextButton.querySelector('button') || nextButton;
                btn.click();

                // 5. 解锁状态 (虽然页面通常会跳转，但为了保险)
                setTimeout(() => { isTyping = false; }, 5000);
            }
        }
    }

    // 核心函数：模拟人工打字（带随机延迟）
    async function typeStringSimulate(element, text) {
        // 获取原生 Setter，防止 React/Angular 劫持导致无法触发 onChange
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;

        for (let i = 0; i < text.length; i++) {
            const char = text[i];
            const currentVal = element.value;

            // 模拟随机打字间隔 (50ms - 150ms)
            const delay = Math.floor(Math.random() * 100) + 50;
            await sleep(delay);

            // 写入新值
            const nextVal = currentVal + char;
            nativeInputValueSetter.call(element, nextVal);

            // 触发必要的输入事件，让网页"知道"用户在输入
            element.dispatchEvent(new Event('input', { bubbles: true }));
            // 可选：如果有些网页监听 keydown/keypress，可以在这里补充，但通常 input 事件足矣
        }

        // 输完后触发 change
        element.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    // ================= 场景 3: Labs 业务页 =================
    // 页面: https://labs.google/fx/*
    function handleLabsGoogle() {
        console.log("[Flow2API Sync] 脚本已加载，3秒后执行同步...");
        setTimeout(syncToken, 3000);

        // 定时刷新页面保活
        const minutes = CONFIG.RELOAD_INTERVAL / 1000 / 60;
        console.log(`[Flow2API Sync] ⏳ 页面将在 ${minutes} 分钟后刷新以更新 Session...`);

        setTimeout(() => {
            console.log("[Flow2API Sync] 🔄 正在刷新页面...");
            window.location.reload();
        }, CONFIG.RELOAD_INTERVAL);
    }

    function syncToken() {
        GM_cookie.list({ name: '__Secure-next-auth.session-token' }, function(cookies, error) {
            if (error) { console.error("[Flow2API Sync] 读取 Cookie 失败:", error); return; }

            if (cookies && cookies.length > 0) {
                const st = cookies[0].value;
                sendTokenToServer(st);
            } else {
                console.log("[Flow2API Sync] 未找到 Session Token，可能未登录");
            }
        });
    }

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
                            console.log(`[Flow2API Sync] ✅ 同步成功! 邮箱: ${data.data.email}`);
                        }
                    } catch (e) {}
                }
            }
        });
    }

})();