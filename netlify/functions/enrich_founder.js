/**
 * Netlify Serverless Function: enrich_founder.js
 * Runs lightweight founder enrichment using OpenRouter AI.
 */
const axios = require('axios');

exports.handler = async (event) => {
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
        const { title, url, desc } = body;
        if (!title || !url) {
            return { statusCode: 400, headers, body: JSON.stringify({ error: 'Missing parameters' }) };
        }

        const API_KEY = process.env.OPENROUTER_API_KEY;
        const MODEL = process.env.S3_MODEL || "openai/gpt-4o-mini";

        if (!API_KEY) {
            return { statusCode: 500, headers, body: JSON.stringify({ ok: false, error: 'OpenRouter API Key missing' }) };
        }

        const prompt = `请深度调研以下AI产品创始人的背景信息，在中文下进行紧凑摘要：
产品名：${title}
官网：${url}
简介：${desc}

必须发掘：
1. 创始人是谁 (Name)
2. 教育背景（毕业学校、博士/硕士等级）
3. 过往经历（ex-OpenAI, ex-Vercel, ex-Google等顶级公司背景）
4. 是否有华人背景（Chinese heritage）
5. 融资历史与机构（Rounds, Valuation, Lead Investors）
如果未发掘到，请说明“信息量不足独立判断”。输出全中文，专有名词英文表示。`;

        const resp = await axios.post(
            'https://openrouter.ai/api/v1/chat/completions',
            {
                model: MODEL,
                messages: [{ role: 'user', content: prompt }],
                temperature: 0.3,
                max_tokens: 600
            },
            {
                headers: {
                    'Authorization': `Bearer ${API_KEY}`,
                    'Content-Type': 'application/json',
                    'HTTP-Referer': 'https://creekstone.vc',
                    'X-Title': 'CreekstoneRadarEnricher'
                },
                timeout: 25000
            }
        );

        if (resp.data.choices && resp.data.choices[0]) {
            const content = resp.data.choices[0].message.content;
            return { statusCode: 200, headers, body: JSON.stringify({ ok: true, text: content.trim() }) };
        } else {
            return { statusCode: 500, headers, body: JSON.stringify({ ok: false, error: 'AI output format error' }) };
        }

    } catch (err) {
        return { statusCode: 500, headers, body: JSON.stringify({ ok: false, error: err.message }) };
    }
};
