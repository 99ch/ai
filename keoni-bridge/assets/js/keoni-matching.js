(function(){const settings=window.KeoniMatching||{};document.addEventListener('click',event=>{const resetButton=event.target.closest('[data-keoni-reset]');if(resetButton){event.preventDefault();if(resetButton.dataset.loading==='1')return;const ajaxUrl=settings.ajaxUrl;if(!ajaxUrl)return;const container=resetButton.closest('.keoni-matching-wrapper');if(!container)return;const list=container.querySelector('.keoni-matching');const confirmText=resetButton.dataset.confirmText||'';if(confirmText&&typeof window.confirm==='function'){if(!window.confirm(confirmText))return;}const params=new URLSearchParams();params.append('action','keoni_bridge_reset_matching');params.append('nonce',resetButton.dataset.nonce||'');params.append('job_id',resetButton.dataset.jobId||'');resetButton.dataset.loading='1';const defaultText=resetButton.dataset.defaultText||'Réinitialiser les résultats IA';resetButton.textContent=resetButton.dataset.loadingText||'Réinitialisation...';fetch(ajaxUrl,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'},body:params.toString()}).then(resp=>resp.json()).then(result=>{resetButton.dataset.loading='0';resetButton.textContent=defaultText;if(!result||!result.success){const msg=result?.data?.message||'Erreur lors de la réinitialisation.';throw new Error(msg);}if(list){list.innerHTML='';}const empty=document.createElement('div');empty.className='keoni-matching__empty';empty.textContent='Résultats IA supprimés. Relancez le matching pour régénérer.';if(list){list.appendChild(empty);}const loadMore=container.querySelector('[data-keoni-load-more]');if(loadMore){loadMore.remove();}}).catch((error)=>{resetButton.dataset.loading='0';resetButton.textContent=defaultText;const message=error?.message||'Erreur lors de la réinitialisation.';if(list){const empty=document.createElement('div');empty.className='keoni-matching__empty';empty.textContent=message;list.prepend(empty);}else if(typeof window.alert==='function'){window.alert(message);}});return;}const button=event.target.closest('[data-keoni-load-more]');if(!button)return;event.preventDefault();if(button.dataset.loading==='1')return;const ajaxUrl=settings.ajaxUrl;if(!ajaxUrl)return;const container=button.closest('.keoni-matching-wrapper');if(!container)return;const list=container.querySelector('.keoni-matching');if(!list)return;const limit=parseInt(button.dataset.limit||'20',10);const offset=parseInt(button.dataset.offset||'0',10);const params=new URLSearchParams();params.append('action','keoni_matching_load_more');params.append('nonce',button.dataset.nonce||'');params.append('job_id',button.dataset.jobId||'');params.append('limit',String(limit));params.append('offset',String(offset));params.append('min_score',button.dataset.minScore||'0');button.dataset.loading='1';const defaultText=button.dataset.defaultText||'Afficher plus';button.textContent=button.dataset.loadingText||'Chargement...';fetch(ajaxUrl,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'},body:params.toString()}).then(resp=>resp.json()).then(result=>{button.dataset.loading='0';button.textContent=defaultText;if(!result||!result.success){throw new Error(result?.data?.message||'Erreur');}const data=result.data||{};if(!data.html){button.remove();return;}const template=document.createElement('template');template.innerHTML=data.html.trim();list.appendChild(template.content);list.dispatchEvent(new Event('keoni-matching:cards-appended',{bubbles:true}));if(data.has_more){button.dataset.offset=String(data.next_offset ?? (offset+limit));button.dataset.limit=String(data.limit ?? limit);}else{button.remove();}}).catch(()=>{button.dataset.loading='0';button.textContent=defaultText;});});})();

// Filtre live par score minimum : purement côté client (aucun aller-retour
// serveur), applique/enlève une classe qui masque les cartes déjà présentes
// dans le DOM en fonction de leur data-score. Une IIFE séparée de celle
// ci-dessus (au lieu d'y être insérée) pour rester lisible sans reformater
// le bloc dense existant.
(function () {
    function updateFilter(wrapper) {
        var slider = wrapper.querySelector('[data-keoni-score-slider]');
        if (!slider) {
            return;
        }

        var valueLabel = wrapper.querySelector('[data-keoni-score-value]');
        var countLabel = wrapper.querySelector('[data-keoni-score-count]');
        var emptyState = wrapper.querySelector('[data-keoni-score-empty]');
        var minScore = parseFloat(slider.value) || 0;

        if (valueLabel) {
            valueLabel.textContent = String(Math.round(minScore));
        }

        var cards = wrapper.querySelectorAll('.keoni-matching__card');
        var visibleCount = 0;

        cards.forEach(function (card) {
            var score = parseFloat(card.dataset.score || '0');
            var visible = score >= minScore;
            card.classList.toggle('keoni-matching__card--filtered-out', !visible);
            if (visible) {
                visibleCount++;
            }
        });

        if (countLabel) {
            countLabel.textContent = cards.length ? (visibleCount + ' / ' + cards.length) : '';
        }

        if (emptyState) {
            emptyState.hidden = cards.length === 0 || visibleCount > 0;
        }
    }

    document.addEventListener('input', function (event) {
        var slider = event.target.closest('[data-keoni-score-slider]');
        if (!slider) {
            return;
        }
        var wrapper = slider.closest('.keoni-matching-wrapper');
        if (wrapper) {
            updateFilter(wrapper);
        }
    });

    // "Afficher plus" charge de nouvelles cartes en AJAX après coup --
    // leur appliquer le seuil actuellement choisi, pas seulement celles
    // présentes au premier rendu (voir le dispatchEvent ajouté ci-dessus).
    document.addEventListener('keoni-matching:cards-appended', function (event) {
        var wrapper = event.target.closest ? event.target.closest('.keoni-matching-wrapper') : null;
        if (wrapper) {
            updateFilter(wrapper);
        }
    });

    document.querySelectorAll('.keoni-matching-wrapper').forEach(updateFilter);
})();
