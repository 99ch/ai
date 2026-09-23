(function () {
	var settings = window.KeoniMatching || {};

	function getModalEls() {
		var modal = document.getElementById('keoni-matching-modal');
		if (!modal) return null;
		return {
			modal: modal,
			title: document.getElementById('keoni-matching-modal-title'),
			body: document.getElementById('keoni-matching-modal-body'),
		};
	}

	// La modale est en position:fixed par-dessus la page, mais ça ne
	// bloque pas le scroll du <body> en dessous : un geste de scroll
	// (molette/trackpad/tactile) fait défiler l'arrière-plan en même
	// temps que le contenu de la modale. On verrouille le scroll de la
	// page tant qu'une modale est ouverte, et on restaure la position de
	// scroll d'origine à la fermeture (position:fixed sur le body sinon
	// la page remonte en haut).
	var lockedScrollY = 0;
	var isLocked = false;

	function lockBodyScroll() {
		if (isLocked) return; // ex: un 2e clic ouvre un autre candidat sans repasser par closeModal()
		isLocked = true;
		lockedScrollY = window.scrollY;
		document.body.style.position = 'fixed';
		document.body.style.top = '-' + lockedScrollY + 'px';
		document.body.style.left = '0';
		document.body.style.right = '0';
		document.body.style.width = '100%';
	}

	function unlockBodyScroll() {
		if (!isLocked) return;
		isLocked = false;
		document.body.style.position = '';
		document.body.style.top = '';
		document.body.style.left = '';
		document.body.style.right = '';
		document.body.style.width = '';
		window.scrollTo(0, lockedScrollY);
	}

	// Contour rouge sur le bouton juste cliqué, pour le retrouver après
	// coup dans la liste des cartes (persiste après la fermeture de la
	// modale -- retiré seulement quand un autre bouton est cliqué).
	var lastClickedButton = null;

	function markLastClicked(button) {
		if (lastClickedButton && lastClickedButton !== button) {
			lastClickedButton.classList.remove('keoni-matching__btn--last-clicked');
		}
		button.classList.add('keoni-matching__btn--last-clicked');
		lastClickedButton = button;
	}

	function openModal(title, contentNode) {
		var els = getModalEls();
		if (!els) return;
		els.title.textContent = title || '';
		els.body.innerHTML = '';
		if (contentNode) els.body.appendChild(contentNode);
		els.modal.hidden = false;
		lockBodyScroll();
	}

	function closeModal() {
		var els = getModalEls();
		if (!els) return;
		els.modal.hidden = true;
		els.body.innerHTML = '';
		unlockBodyScroll();
	}

	function textNode(className, text) {
		var el = document.createElement('p');
		el.className = className;
		el.textContent = text;
		return el;
	}

	// Rendu partagé pour "Voir le CV extrait" et "Job extrait" (Analyse
	// IA texte+compétences, même forme de réponse côté PHP pour les deux
	// actions -- voir ajax_extract_cv()/ajax_extract_job()).
	function renderExtractResult(data) {
		var wrap = document.createElement('div');
		wrap.appendChild(textNode('keoni-matching__structured-text', data.text || 'Aucun texte exploitable.'));
		if (Array.isArray(data.skills) && data.skills.length) {
			var skillsWrap = document.createElement('div');
			skillsWrap.className = 'keoni-matching__resume-keywords';
			data.skills.forEach(function (skill) {
				var span = document.createElement('span');
				span.textContent = skill;
				skillsWrap.appendChild(span);
			});
			wrap.appendChild(skillsWrap);
		}
		return wrap;
	}

	function runExtract(button, action, extraParams) {
		var ajaxUrl = settings.ajaxUrl;
		if (!ajaxUrl) return;
		var title = button.dataset.modalTitle || '';
		markLastClicked(button);

		if (button.dataset.cachedHtml) {
			var cached = document.createElement('div');
			cached.innerHTML = button.dataset.cachedHtml;
			openModal(title, cached);
			return;
		}

		if (button.dataset.loading === '1') return;

		var defaultText = button.dataset.defaultText || button.textContent;
		button.dataset.loading = '1';
		button.disabled = true;
		button.textContent = button.dataset.loadingText || 'Analyse...';

		var params = new URLSearchParams();
		params.append('action', action);
		params.append('nonce', button.dataset.nonce || '');
		Object.keys(extraParams).forEach(function (key) {
			params.append(key, extraParams[key]);
		});

		fetch(ajaxUrl, {
			method: 'POST',
			headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
			body: params.toString(),
		})
			.then(function (resp) { return resp.json(); })
			.then(function (result) {
				button.dataset.loading = '0';
				button.disabled = false;
				button.textContent = defaultText;
				if (!result || !result.success) {
					throw new Error((result && result.data && result.data.message) || "Erreur lors de l'analyse.");
				}
				var data = result.data || {};
				var content = renderExtractResult(data);
				button.dataset.cachedHtml = content.innerHTML;
				openModal(title, content);
			})
			.catch(function (error) {
				button.dataset.loading = '0';
				button.disabled = false;
				button.textContent = defaultText;
				openModal(title, textNode('keoni-matching__muted', (error && error.message) || "Erreur lors de l'analyse."));
			});
	}

	document.addEventListener('click', function (event) {
		if (event.target.closest('[data-keoni-modal-close]')) {
			event.preventDefault();
			closeModal();
			return;
		}

		var explainButton = event.target.closest('[data-keoni-open-explain]');
		if (explainButton) {
			event.preventDefault();
			markLastClicked(explainButton);
			var card = explainButton.closest('.keoni-matching__card');
			var template = card ? card.querySelector('.keoni-matching__explain-data') : null;
			if (!template) return;
			var content = document.importNode(template.content, true);
			openModal(explainButton.dataset.modalTitle || 'Analyse', content);
			return;
		}

		var cvButton = event.target.closest('[data-keoni-open-cv]');
		if (cvButton) {
			event.preventDefault();
			markLastClicked(cvButton);
			var cvUrl = cvButton.dataset.cvUrl;
			if (!cvUrl) return;
			var iframe = document.createElement('iframe');
			iframe.src = cvUrl;
			iframe.title = cvButton.dataset.modalTitle || 'CV';
			openModal(cvButton.dataset.modalTitle || 'CV', iframe);
			return;
		}

		var extractCvButton = event.target.closest('[data-keoni-extract-cv]');
		if (extractCvButton) {
			event.preventDefault();
			runExtract(extractCvButton, 'keoni_bridge_extract_cv', {
				cv_id: extractCvButton.dataset.cvId || '',
				job_id: extractCvButton.dataset.jobId || '',
			});
			return;
		}

		var extractJobButton = event.target.closest('[data-keoni-extract-job]');
		if (extractJobButton) {
			event.preventDefault();
			runExtract(extractJobButton, 'keoni_bridge_extract_job', {
				job_id: extractJobButton.dataset.jobId || '',
			});
			return;
		}

		var resetButton = event.target.closest('[data-keoni-reset]');
		if (resetButton) {
			event.preventDefault();
			if (resetButton.dataset.loading === '1') return;
			var ajaxUrl = settings.ajaxUrl;
			if (!ajaxUrl) return;
			var container = resetButton.closest('.keoni-matching-wrapper');
			if (!container) return;
			var list = container.querySelector('.keoni-matching');
			var confirmText = resetButton.dataset.confirmText || '';
			if (confirmText && typeof window.confirm === 'function') {
				if (!window.confirm(confirmText)) return;
			}
			var params = new URLSearchParams();
			params.append('action', 'keoni_bridge_reset_matching');
			params.append('nonce', resetButton.dataset.nonce || '');
			params.append('job_id', resetButton.dataset.jobId || '');
			resetButton.dataset.loading = '1';
			var defaultText = resetButton.dataset.defaultText || 'Réinitialiser les résultats IA';
			resetButton.textContent = resetButton.dataset.loadingText || 'Réinitialisation...';
			fetch(ajaxUrl, {
				method: 'POST',
				headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
				body: params.toString(),
			})
				.then(function (resp) { return resp.json(); })
				.then(function (result) {
					resetButton.dataset.loading = '0';
					resetButton.textContent = defaultText;
					if (!result || !result.success) {
						throw new Error((result && result.data && result.data.message) || 'Erreur lors de la réinitialisation.');
					}
					if (list) list.innerHTML = '';
					var empty = document.createElement('div');
					empty.className = 'keoni-matching__empty';
					empty.textContent = 'Résultats IA supprimés. Relancez le matching pour régénérer.';
					if (list) list.appendChild(empty);
					var loadMore = container.querySelector('[data-keoni-load-more]');
					if (loadMore) loadMore.remove();
				})
				.catch(function (error) {
					resetButton.dataset.loading = '0';
					resetButton.textContent = defaultText;
					var message = (error && error.message) || 'Erreur lors de la réinitialisation.';
					if (list) {
						var empty = document.createElement('div');
						empty.className = 'keoni-matching__empty';
						empty.textContent = message;
						list.prepend(empty);
					} else if (typeof window.alert === 'function') {
						window.alert(message);
					}
				});
			return;
		}

		var loadMoreButton = event.target.closest('[data-keoni-load-more]');
		if (loadMoreButton) {
			event.preventDefault();
			if (loadMoreButton.dataset.loading === '1') return;
			var ajaxUrl2 = settings.ajaxUrl;
			if (!ajaxUrl2) return;
			var container2 = loadMoreButton.closest('.keoni-matching-wrapper');
			if (!container2) return;
			var list2 = container2.querySelector('.keoni-matching');
			if (!list2) return;
			var limit = parseInt(loadMoreButton.dataset.limit || '20', 10);
			var offset = parseInt(loadMoreButton.dataset.offset || '0', 10);
			var params2 = new URLSearchParams();
			params2.append('action', 'keoni_matching_load_more');
			params2.append('nonce', loadMoreButton.dataset.nonce || '');
			params2.append('job_id', loadMoreButton.dataset.jobId || '');
			params2.append('limit', String(limit));
			params2.append('offset', String(offset));
			params2.append('min_score', loadMoreButton.dataset.minScore || '0');
			loadMoreButton.dataset.loading = '1';
			var defaultText2 = loadMoreButton.dataset.defaultText || 'Afficher plus';
			loadMoreButton.textContent = loadMoreButton.dataset.loadingText || 'Chargement...';
			fetch(ajaxUrl2, {
				method: 'POST',
				headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
				body: params2.toString(),
			})
				.then(function (resp) { return resp.json(); })
				.then(function (result) {
					loadMoreButton.dataset.loading = '0';
					loadMoreButton.textContent = defaultText2;
					if (!result || !result.success) {
						throw new Error((result && result.data && result.data.message) || 'Erreur');
					}
					var data = result.data || {};
					if (!data.html) {
						loadMoreButton.remove();
						return;
					}
					var template2 = document.createElement('template');
					template2.innerHTML = data.html.trim();
					list2.appendChild(template2.content);
					if (data.has_more) {
						loadMoreButton.dataset.offset = String(data.next_offset != null ? data.next_offset : (offset + limit));
						loadMoreButton.dataset.limit = String(data.limit != null ? data.limit : limit);
					} else {
						loadMoreButton.remove();
					}
				})
				.catch(function () {
					loadMoreButton.dataset.loading = '0';
					loadMoreButton.textContent = defaultText2;
				});
			return;
		}
	});

	document.addEventListener('keydown', function (event) {
		if (event.key !== 'Escape') return;
		var els = getModalEls();
		if (els && !els.modal.hidden) closeModal();
	});
})();
