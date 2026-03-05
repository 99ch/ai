(function () {
	const settings = window.KeoniMatching || {};

	function getList(container) {
		return container ? container.querySelector('.keoni-matching') : null;
	}

	function getActiveFilter(container) {
		const active = container.querySelector('[data-keoni-filter].is-active');
		return active ? active.dataset.keoniFilter : 'all';
	}

	function cardMatchesFilter(card, filter) {
		const score = Number.parseFloat(card.dataset.score || '0');
		const qualified = card.dataset.qualified === '1';
		const level = card.dataset.matchLevel || '';

		if (filter === 'qualified') {
			return qualified || score >= 50;
		}

		if (filter === 'strong') {
			return level === 'strong' || score >= 80;
		}

		return true;
	}

	function getOrCreateFilterEmpty(container) {
		let empty = container.querySelector('.keoni-matching__empty--filter');
		if (empty) {
			return empty;
		}

		empty = document.createElement('div');
		empty.className = 'keoni-matching__empty keoni-matching__empty--filter';
		empty.textContent = 'Aucun candidat pour ce filtre.';
		empty.hidden = true;

		const list = getList(container);
		if (list) {
			list.insertAdjacentElement('afterend', empty);
		}

		return empty;
	}

	function applyActiveFilter(container) {
		const list = getList(container);
		if (!list) {
			return;
		}

		const filter = getActiveFilter(container);
		const cards = list.querySelectorAll('.keoni-matching__card');
		let visibleCount = 0;

		cards.forEach((card) => {
			const visible = cardMatchesFilter(card, filter);
			card.hidden = !visible;
			if (visible) {
				visibleCount += 1;
			}
		});

		const empty = getOrCreateFilterEmpty(container);
		empty.hidden = !(cards.length > 0 && visibleCount === 0);
	}

	function handleReset(button) {
		if (button.dataset.loading === '1') {
			return;
		}

		const ajaxUrl = settings.ajaxUrl;
		if (!ajaxUrl) {
			return;
		}

		const container = button.closest('.keoni-matching-wrapper');
		if (!container) {
			return;
		}

		const list = getList(container);
		const confirmText = button.dataset.confirmText || '';

		if (confirmText && typeof window.confirm === 'function' && !window.confirm(confirmText)) {
			return;
		}

		const params = new URLSearchParams();
		params.append('action', 'keoni_bridge_reset_matching');
		params.append('nonce', button.dataset.nonce || '');
		params.append('job_id', button.dataset.jobId || '');

		button.dataset.loading = '1';
		const defaultText = button.dataset.defaultText || 'Réinitialiser les résultats IA';
		button.textContent = button.dataset.loadingText || 'Réinitialisation...';

		fetch(ajaxUrl, {
			method: 'POST',
			headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
			body: params.toString(),
		})
			.then((resp) => resp.json())
			.then((result) => {
				button.dataset.loading = '0';
				button.textContent = defaultText;

				if (!result || !result.success) {
					const message = result?.data?.message || 'Erreur lors de la réinitialisation.';
					throw new Error(message);
				}

				if (list) {
					list.innerHTML = '';
					const empty = document.createElement('div');
					empty.className = 'keoni-matching__empty';
					empty.textContent = 'Résultats IA supprimés. Relancez le matching pour régénérer.';
					list.appendChild(empty);
				}

				const filterEmpty = container.querySelector('.keoni-matching__empty--filter');
				if (filterEmpty) {
					filterEmpty.remove();
				}

				const loadMore = container.querySelector('[data-keoni-load-more]');
				if (loadMore) {
					loadMore.remove();
				}
			})
			.catch((error) => {
				button.dataset.loading = '0';
				button.textContent = defaultText;

				const message = error?.message || 'Erreur lors de la réinitialisation.';
				if (list) {
					const empty = document.createElement('div');
					empty.className = 'keoni-matching__empty';
					empty.textContent = message;
					list.prepend(empty);
				} else if (typeof window.alert === 'function') {
					window.alert(message);
				}
			});
	}

	function handleLoadMore(button) {
		if (button.dataset.loading === '1') {
			return;
		}

		const ajaxUrl = settings.ajaxUrl;
		if (!ajaxUrl) {
			return;
		}

		const container = button.closest('.keoni-matching-wrapper');
		const list = getList(container);

		if (!container || !list) {
			return;
		}

		const limit = Number.parseInt(button.dataset.limit || '20', 10);
		const offset = Number.parseInt(button.dataset.offset || '0', 10);

		const params = new URLSearchParams();
		params.append('action', 'keoni_matching_load_more');
		params.append('nonce', button.dataset.nonce || '');
		params.append('job_id', button.dataset.jobId || '');
		params.append('limit', String(limit));
		params.append('offset', String(offset));
		params.append('min_score', button.dataset.minScore || '0');

		button.dataset.loading = '1';
		const defaultText = button.dataset.defaultText || 'Afficher plus';
		button.textContent = button.dataset.loadingText || 'Chargement...';

		fetch(ajaxUrl, {
			method: 'POST',
			headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
			body: params.toString(),
		})
			.then((resp) => resp.json())
			.then((result) => {
				button.dataset.loading = '0';
				button.textContent = defaultText;

				if (!result || !result.success) {
					throw new Error(result?.data?.message || 'Erreur');
				}

				const data = result.data || {};
				if (!data.html) {
					button.remove();
					return;
				}

				const template = document.createElement('template');
				template.innerHTML = data.html.trim();
				list.appendChild(template.content);
				applyActiveFilter(container);

				if (data.has_more) {
					button.dataset.offset = String(data.next_offset ?? offset + limit);
					button.dataset.limit = String(data.limit ?? limit);
				} else {
					button.remove();
				}
			})
			.catch(() => {
				button.dataset.loading = '0';
				button.textContent = defaultText;
			});
	}

	function initializeFilters() {
		document.querySelectorAll('.keoni-matching-wrapper').forEach((container) => {
			applyActiveFilter(container);
		});
	}

	document.addEventListener('click', (event) => {
		const resetButton = event.target.closest('[data-keoni-reset]');
		if (resetButton) {
			event.preventDefault();
			handleReset(resetButton);
			return;
		}

		const filterButton = event.target.closest('[data-keoni-filter]');
		if (filterButton) {
			event.preventDefault();
			const container = filterButton.closest('.keoni-matching-wrapper');
			if (!container) {
				return;
			}

			container.querySelectorAll('[data-keoni-filter]').forEach((button) => {
				button.classList.toggle('is-active', button === filterButton);
			});

			applyActiveFilter(container);
			return;
		}

		const loadMoreButton = event.target.closest('[data-keoni-load-more]');
		if (loadMoreButton) {
			event.preventDefault();
			handleLoadMore(loadMoreButton);
		}
	});

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', initializeFilters);
	} else {
		initializeFilters();
	}
})();
