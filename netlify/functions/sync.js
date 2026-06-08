/**
 * Netlify Serverless Function: sync.js
 * Synchronizes selected product information to Feishu Bitable.
 */
const axios = require('axios');

exports.handler = async (event) => {
    // Enable CORS
    const headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Methods': 'POST, OPTIONS'
    };

    if (event.httpMethod === 'OPTIONS') {
        return { statusCode: 200, headers, body: '' };
    }

    if (event.httpMethod !== 'POST') {
        return { statusCode: 405, headers, body: JSON.stringify({ error: 'Method Not Allowed' }) };
    }

    try {
        const body = JSON.parse(event.body || '{}');
        const item = body.item;
        if (!item || !item.t || !item.u) {
            return { statusCode: 400, headers, body: JSON.stringify({ error: 'Invalid Item Data' }) };
        }

        // Credentials from netlify configuration settings
        const APP_ID = process.env.FEISHU_APP_ID;
        const APP_SECRET = process.env.FEISHU_APP_SECRET;
        const BASE_TOKEN = process.env.BITABLE_APP_TOKEN;
        const TABLE_ID = process.env.BITABLE_TABLE_ID;

        const webHook = process.env.FEISHU_WEBHOOK_URL;

        if (!APP_ID || !APP_SECRET || !BASE_TOKEN || !TABLE_ID) {
            return {
                statusCode: 400,
                headers,
                body: JSON.stringify({ error: 'Credentials Missing', ok: false })
            };
        }

        // 1. Get Tenant Access Token
        const tokenResp = await axios.post(
            'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
            { app_id: APP_ID, app_secret: APP_SECRET },
            { timeout: 8000 }
        );
        const token = tokenResp.data.tenant_access_token;
        if (!token) throw new Error('Token generation failed');

        // 2. Map fields to Bitable schema
        const fp = item.fp || {};
        const tm = item.tm || {};
        const sb = item.sb || {};
        
        let emoji = "⚪";
        if (item.tr === "A") emoji = "🔵";
        else if (item.tr === "B") emoji = "🟢";
        else if (item.tr === "C") emoji = "🟡";
        else if (item.tr === "Hardware") emoji = "🔩";
        else if (item.tr === "Tech") emoji = "🔬";
        else if (item.tr === "Multimodal") emoji = "🎬";
        else if (item.tr === "Lifestyle") emoji = "💜";

        const fields = {
            "项目名称": item.t,
            "URL": item.u,
            "来源": item.src,
            "Track": `${emoji} ${item.tr}`,
            "评分": item.sc,
            "一句话介绍": fp.ol || item.tr_rs || '',
            "核心摘要": fp.ov || '',
            "商业模式": fp.bm || '',
            "Creekstone视角": fp.is || '',
            "评分逻辑": fp.sn || '',
            "数据指标": fp.ms || '',
            "关键词": (item.kws || []).join(', '),
            "Founder信息": (tm.fds || []).join(' / ') + (fp.fd ? `\n\n${fp.fd}` : ''),
            "融资信息": tm.fin || '',
            "是否华人创始人": tm.ch ? "是" : "待确认",
            "收录日期": (item.at || '').substring(0, 10),
            "状态": "待跟进",
            "来源原始ID": item.id
        };

        if (sb && sb.total) {
            fields["评分明细"] = `AI Native:${sb.ai}/30 · Niche:${sb.nc}/25 · 商业:${sb.bz}/20 · 团队:${sb.tm}/15 · 加减分:${sb.bp}`;
        }

        // 3. Write row into Bitable via open API
        const bitableUrl = `https://open.feishu.cn/open-apis/bitable/v1/apps/${BASE_TOKEN}/tables/${TABLE_ID}/records`;
        const bitableResp = await axios.post(
            bitableUrl,
            { fields },
            {
                headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                timeout: 8000
            }
        );

        if (bitableResp.data.code === 0) {
            // Optional: push card notifications back to feishu webhook
            if (webHook) {
                try {
                    await axios.post(webHook, {
                        msg_type: "text",
                        content: { text: `◈ Gary跟进了项目「${item.t}」(${item.sc}分)已自动同步到 Sourcing 底表` }
                    }, { timeout: 3000 });
                } catch(e) {}
            }

            return { statusCode: 200, headers, body: JSON.stringify({ ok: true, msg: 'Sync successful' }) };
        } else {
            return { statusCode: 500, headers, body: JSON.stringify({ ok: false, error: bitableResp.data.msg }) };
        }

    } catch (err) {
        return { statusCode: 500, headers, body: JSON.stringify({ ok: false, error: err.message }) };
    }
};
