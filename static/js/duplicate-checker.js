/**
 * Duplicate Checker - Reusable duplicate detection for contacts and items
 * Handles duplicate warnings, fuzzy matching, and merge functionality
 */

class DuplicateChecker {
    constructor(config) {
        this.type = config.type; // 'contact' or 'item'
        this.checkUrl = config.checkUrl;
        this.mergeUrl = config.mergeUrl;
        this.reactivateUrl = config.reactivateUrl;
        this.redirectUrl = config.redirectUrl;
        this.getFormData = config.getFormData; // Function to get current form data
        this.urlPrefix = config.urlPrefix || '';

        this.duplicateModal = null;
        this.fuzzyModal = null;
        this.currentDuplicateData = null;
        this.duplicateAcknowledged = false;

        this.init();
    }

    init() {
        // Initialize modals
        const dupModalEl = document.getElementById('duplicateModal');
        const fuzzyModalEl = document.getElementById('fuzzyModal');

        if (dupModalEl) {
            this.duplicateModal = new bootstrap.Modal(dupModalEl);
        }
        if (fuzzyModalEl) {
            this.fuzzyModal = new bootstrap.Modal(fuzzyModalEl);
        }

        // Setup event listeners
        this.setupEventListeners();
    }

    setupEventListeners() {
        const self = this;

        // Only attach listeners once by checking if already attached
        const modalEl = document.getElementById('duplicateModal');
        if (modalEl && !modalEl.dataset.listenersAttached) {
            modalEl.dataset.listenersAttached = 'true';

            // Handle button clicks and manually dismiss modal
            modalEl.addEventListener('click', function(e) {
                const dismissBtn = e.target.closest('[data-bs-dismiss="modal"]');
                if (!dismissBtn) return;

                const buttonText = dismissBtn.textContent.trim();
                console.log('[DuplicateChecker] Button clicked:', buttonText);

                if (buttonText.includes('Add as Duplicate')) {
                    e.preventDefault();
                    e.stopPropagation();
                    console.log('[DuplicateChecker] Add as Duplicate - closing modal');
                    self.duplicateAcknowledged = true;
                    self.duplicateModal.hide();
                } else if (buttonText.includes('Cancel')) {
                    e.preventDefault();
                    e.stopPropagation();
                    console.log('[DuplicateChecker] Cancel - closing modal');
                    // Only redirect if NOT on the loan page
                    if (self.redirectUrl && !self.redirectUrl.includes('loan')) {
                        self.duplicateModal.hide();
                        setTimeout(function() {
                            window.location.href = self.redirectUrl;
                        }, 300);
                    } else {
                        self.duplicateModal.hide();
                    }
                } else if (buttonText === '' || dismissBtn.classList.contains('btn-close')) {
                    // X button
                    e.preventDefault();
                    e.stopPropagation();
                    console.log('[DuplicateChecker] X button - closing modal');
                    self.duplicateModal.hide();
                }
            });
        }

        // Merge button
        const mergeBtn = document.getElementById('merge_btn');
        if (mergeBtn) {
            mergeBtn.addEventListener('click', function() {
                self.handleMerge();
            });
        }

        // Re-add button (for soft-deleted items)
        const readdBtn = document.getElementById('readd_btn');
        if (readdBtn) {
            readdBtn.addEventListener('click', function() {
                self.handleReactivate();
            });
        }
    }

    async check() {
        if (this.duplicateAcknowledged) {
            return; // Skip check if already acknowledged
        }

        const formData = this.getFormData();

        // Don't check if required fields are empty
        if (!formData.name || !formData.name.trim()) {
            return;
        }

        try {
            const response = await fetch(this.checkUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });

            const data = await response.json();

            if (data.exists) {
                if (data.fuzzy) {
                    this.showFuzzyMatches(data.matches, formData);
                } else {
                    this.currentDuplicateData = data;
                    this.showDuplicateWarning(data.contact || data.item, data.has_new_info, formData);
                }
            }
        } catch (error) {
            console.error('Error checking duplicate:', error);
        }
    }

    showFuzzyMatches(matches, newData) {
        const container = document.getElementById('fuzzy_matches');
        container.innerHTML = '';

        const self = this;
        matches.forEach(function(match) {
            const item = document.createElement('a');
            item.href = '#';
            item.className = 'list-group-item list-group-item-action';
            item.onclick = function(e) {
                e.preventDefault();
                self.fuzzyModal.hide();

                self.currentDuplicateData = {
                    contact: self.type === 'contact' ? match : undefined,
                    item: self.type === 'item' ? match : undefined,
                    has_new_info: self.checkHasNewInfo(match, newData),
                    new_data: newData
                };
                self.showDuplicateWarning(match, self.currentDuplicateData.has_new_info, newData);
            };

            item.innerHTML = self.formatMatchHtml(match);
            container.appendChild(item);
        });

        this.fuzzyModal.show();
    }

    showDuplicateWarning(entity, hasNewInfo, newData) {
        const isActive = entity.is_active === 1 || entity.is_active === undefined;

        // Update title and message
        const titleEl = document.getElementById('dupModalTitle');
        const messageEl = document.getElementById('dupModalMessage');

        if (this.type === 'contact') {
            titleEl.textContent = isActive ? 'Contact Already Exists' : 'Previous Contact Found';
            if (isActive) {
                messageEl.innerHTML = 'A contact named <strong>' + entity.name + '</strong> already exists:';
            } else {
                messageEl.innerHTML = '<strong>' + entity.name + '</strong> was a previous contact that was removed. Would you like to re-add them?';
            }
        } else {
            titleEl.textContent = isActive ? 'Item Already Exists' : 'Previous Item Found';
            if (isActive) {
                messageEl.innerHTML = 'An item named <strong>' + entity.name + '</strong> already exists:';
            } else {
                messageEl.innerHTML = 'An item named <strong>' + entity.name + '</strong> was found but is Archived.';
            }
        }

        // Populate info list
        this.populateInfoList(entity);

        // Show/hide buttons based on context
        this.updateModalButtons(isActive, hasNewInfo, newData, entity);

        this.duplicateModal.show();
    }

    populateInfoList(entity) {
        const infoList = document.getElementById('duplicate_info');
        infoList.innerHTML = '';

        if (this.type === 'contact') {
            if (entity.email) {
                const li = document.createElement('li');
                li.textContent = '📧 ' + entity.email;
                infoList.appendChild(li);
            }
            if (entity.phone) {
                const li = document.createElement('li');
                li.textContent = '📱 ' + entity.phone;
                infoList.appendChild(li);
            }
            if (!entity.email && !entity.phone) {
                const li = document.createElement('li');
                li.textContent = 'No contact information on file';
                li.className = 'text-muted';
                infoList.appendChild(li);
            }
        } else {
            // Item
            if (entity.description) {
                const li = document.createElement('li');
                li.textContent = '📝 Description: ' + entity.description;
                infoList.appendChild(li);
            }
            if (entity.photo_uri_thumb || entity.photo_uri) {
                const li = document.createElement('li');
                li.textContent = '📷 Has photo';
                infoList.appendChild(li);

                // Show photo if elements exist
                const photoImg = document.getElementById('duplicate_photo_img');
                const photoDiv = document.getElementById('duplicate_photo');
                if (photoImg && photoDiv) {
                    photoImg.src = entity.photo_uri_thumb || entity.photo_uri;
                    photoDiv.style.display = 'block';
                }
            } else {
                const photoDiv = document.getElementById('duplicate_photo');
                if (photoDiv) {
                    photoDiv.style.display = 'none';
                }
            }
            if (!entity.description && !entity.photo_uri_thumb && !entity.photo_uri) {
                const li = document.createElement('li');
                li.textContent = 'No additional information';
                li.className = 'text-muted';
                infoList.appendChild(li);
            }
        }
    }

    updateModalButtons(isActive, hasNewInfo, newData, entity) {
        const readdBtn = document.getElementById('readd_btn');
        const editBtn = document.getElementById('edit_existing_btn');
        const mergeBtn = document.getElementById('merge_btn');
        const mergeSuggestion = document.getElementById('merge_suggestion');

        if (isActive) {
            // Active entity
            if (readdBtn) readdBtn.style.display = 'none';
            if (editBtn) {
                editBtn.style.display = 'inline-block';
                editBtn.href = this.getEditUrl(entity.id);
            }

            if (hasNewInfo) {
                this.showMergeSuggestion(entity, newData);
                if (mergeSuggestion) mergeSuggestion.style.display = 'block';
                if (mergeBtn) mergeBtn.style.display = 'inline-block';
            } else {
                if (mergeSuggestion) mergeSuggestion.style.display = 'none';
                if (mergeBtn) mergeBtn.style.display = 'none';
            }
        } else {
            // Soft-deleted entity
            if (readdBtn) readdBtn.style.display = 'none';
            if (editBtn) {
                editBtn.style.display = 'inline-block';
                editBtn.textContent = 'Reactivate';
                editBtn.classList.remove('btn-primary');
                editBtn.classList.add('btn-success');
                editBtn.href = '#';
                // Store entity ID for reactivation
                editBtn.dataset.entityId = entity.id;
                // Wire to reactivate function
                editBtn.onclick = (e) => {
                    e.preventDefault();
                    this.handleReactivateFromEditBtn(entity.id);
                };
            }
            if (mergeSuggestion) mergeSuggestion.style.display = 'none';
            if (mergeBtn) mergeBtn.style.display = 'none';
        }
    }

    showMergeSuggestion(entity, newData) {
        const newInfoList = document.getElementById('new_info_list');
        if (!newInfoList) return;

        newInfoList.innerHTML = '';

        if (this.type === 'contact') {
            if (newData.email && !entity.email) {
                const li = document.createElement('li');
                li.textContent = '📧 ' + newData.email;
                newInfoList.appendChild(li);
            }
            if (newData.phone && !entity.phone) {
                const li = document.createElement('li');
                li.textContent = '📱 ' + newData.phone;
                newInfoList.appendChild(li);
            }
        } else {
            if (newData.description && !entity.description) {
                const li = document.createElement('li');
                li.textContent = '📝 Description: ' + newData.description;
                newInfoList.appendChild(li);
            }
            if (newData.has_photo && !entity.photo_uri_thumb && !entity.photo_uri) {
                const li = document.createElement('li');
                li.textContent = '📷 Photo';
                newInfoList.appendChild(li);
            }
        }
    }

    async handleMerge() {
        if (!this.currentDuplicateData) return;

        const entityData = this.currentDuplicateData.contact || this.currentDuplicateData.item;
        const payload = {};
        payload[this.type + '_id'] = entityData.id;

        if (this.type === 'contact') {
            payload.email = this.currentDuplicateData.new_data.email;
            payload.phone = this.currentDuplicateData.new_data.phone;
        } else {
            payload.description = this.currentDuplicateData.new_data.description;
        }

        const self = this;
        try {
            const response = await fetch(this.mergeUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const result = await response.json();

            if (result.success) {
                this.duplicateModal.hide();

                if (this.type === 'item' && this.currentDuplicateData.new_data.has_photo) {
                    alert('Description merged! Please upload the photo on the edit page.');
                    window.location.href = this.getEditUrl(result.item_id);
                } else {
                    const entityName = this.type.charAt(0).toUpperCase() + this.type.slice(1);
                    window.location.href = this.redirectUrl + '?message=' +
                        encodeURIComponent(entityName + ' updated with new information!');
                }
            } else {
                alert('Error merging: ' + result.error);
            }
        } catch (error) {
            console.error('Error merging:', error);
            alert('Error merging. Please try again.');
        }
    }

    async handleReactivate() {
        const readdBtn = document.getElementById('readd_btn');
        if (!readdBtn) return;

        const entityId = readdBtn.dataset.entityId;
        if (!entityId) return;

        const payload = {};
        payload[this.type + '_id'] = parseInt(entityId);

        const self = this;
        try {
            const response = await fetch(this.reactivateUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const result = await response.json();

            if (result.success) {
                this.duplicateModal.hide();
                window.location.href = this.redirectUrl + '?message=' +
                    encodeURIComponent(result.name + ' has been re-added!');
            } else {
                alert('Could not re-add: ' + result.error);
            }
        } catch (error) {
            console.error('Reactivate error:', error);
            alert('Error re-adding. Please try again.');
        }
    }

    async handleReactivateFromEditBtn(entityId) {
        if (!entityId) return;

        const payload = {};
        payload[this.type + '_id'] = parseInt(entityId);

        try {
            const response = await fetch(this.reactivateUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const result = await response.json();

            if (result.success) {
                this.duplicateModal.hide();
                window.location.href = this.redirectUrl + '?message=' +
                    encodeURIComponent(result.name + ' has been reactivated!');
            } else {
                alert('Could not reactivate: ' + result.error);
            }
        } catch (error) {
            console.error('Reactivate error:', error);
            alert('Error reactivating. Please try again.');
        }
    }

    // Helper methods
    checkHasNewInfo(entity, newData) {
        if (this.type === 'contact') {
            return (newData.email && !entity.email) || (newData.phone && !entity.phone);
        } else {
            return (newData.description && !entity.description) || (newData.has_photo && !entity.photo_uri_thumb && !entity.photo_uri);
        }
    }

    formatMatchHtml(match) {
        let html = '<strong>' + match.name + '</strong><br>';
        if (this.type === 'contact') {
            if (match.email) html += '📧 ' + match.email + '<br>';
            if (match.phone) html += '📱 ' + match.phone;
            if (!match.email && !match.phone) html += '<span class="text-muted">No contact info</span>';
        } else {
            if (match.description) html += '📝 ' + match.description + '<br>';
            if (match.photo_uri_thumb || match.photo_uri) html += '📷 Has photo';
            if (!match.description && !match.photo_uri_thumb && !match.photo_uri) html += '<span class="text-muted">No additional info</span>';
        }
        return html;
    }

    getEditUrl(entityId) {
        let url = this.urlPrefix + '/' + this.type + 's/' + entityId + '/edit';
        // If redirectUrl is loan page, add next parameter
        if (this.redirectUrl && this.redirectUrl.includes('loan')) {
            url += '?next=loan';
        }
        return url;
    }
}
