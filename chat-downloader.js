// ==UserScript==
// @name		YouTube Live Chat Interceptor
// @namespace	ElPsyKongroo
// @version		1.0
// @description	Intercept YouTube live chat and forwards them to a specified server.
// @author		Amelius Dex
// @match		https://www.youtube.com/*
// @grant		none
// ==/UserScript==

(function () {
	'use strict';

	const PORT = 8000
	const PATH = 'forwardedChats'

	class ResponseForwarder {
		constructor(originalResponse) {
			const transform = new TransformStream();
			this.readable = transform.readable;
			this.writer = transform.writable.getWriter();

			this.forwardedResponse = new Response(this.readable, {
				status: originalResponse.status,
				statusText: originalResponse.statusText,
				headers: originalResponse.headers,
			});

			Object.defineProperties(this.forwardedResponse, {
				ok: { value: originalResponse.ok },
				redirected: { value: originalResponse.redirected },
				type: { value: originalResponse.type },
				url: { value: originalResponse.url },
			});

			this.capture(originalResponse.body);
		}

		async capture(body) {
			const reader = body.getReader();
			const decoder = new TextDecoder();
			let result = '';

			while (true) {
				const { done, value } = await reader.read();
				if (done) {
					break;
				}
				result += decoder.decode(value);
			}

			await this.writer.write(new TextEncoder().encode(result));
			this.writer.close();
			this.forward(JSON.parse(result));
		}

		async forward(data) {
			const paramString = window.top.location.href.split('?')[1];
			const videoId = new URLSearchParams(paramString).get('v');
			const wrapped = {
				videoId: videoId,
				data: data,
			};
			try {
				const res = await fetch(`http://localhost:${PORT}/${PATH}`, {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(wrapped),
				});
			} catch (error) {
				console.error(`[Interceptor] Forward failed: ${error}`);
			}
		}
	}

	const originalFetch = window.fetch;

	window.fetch = async function (...args) {
		const url = (typeof args[0] === 'string') ? args[0] : args[0].url;
		const responsePromise = originalFetch.apply(this, args);
		if (url.includes('/youtubei/v1/live_chat/get_live_chat')) {
			const response = await responsePromise;
			const intercept = new ResponseForwarder(response);
			return intercept.forwardedResponse;
		}

		return await responsePromise;
	};
})();
