define('custom:views/lead-detail', ['views/record/detail'], function (DetailRecordView) {
    const statuses = ['New', 'In Process', 'Send Offer', 'Cold Email', 'Converted', 'Recycled', 'Dead'];

    return class extends DetailRecordView {
        events = Object.assign({}, super.events, {
            'keydown .field input, .field textarea, .field select': function (event) {
                if (event.key !== 'Enter') return;
                const target = event.target;
                if (target.tagName === 'TEXTAREA' && event.shiftKey) return;
                if (target.tagName === 'INPUT' && ['button', 'submit', 'checkbox', 'radio'].includes(target.type)) return;
                event.preventDefault();
                event.stopPropagation();
                if (this.mode === this.MODE_EDIT) {
                    this.actionSave();
                    return;
                }
                const field = target.closest('.field[data-name]');
                const name = field && field.dataset.name;
                if (name && this.inlineEditModeIsOn) this.recordHelper.trigger('inline-edit-save', name);
            },
        });

        setup() {
            super.setup();
            this.listenTo(this.model, 'change:status', () => this.updateStatusButtons());
            this.on('after:mode-change', () => this.updateStatusButtons());
        }

        afterRender() {
            super.afterRender();
            this.renderStatusButtons();
        }

        renderStatusButtons() {
            const host = this.element && this.element.querySelector('.middle');
            if (!host || host.querySelector('.lead-status-actions')) return;
            const bar = document.createElement('div');
            bar.className = 'lead-status-actions';
            bar.setAttribute('role', 'group');
            bar.setAttribute('aria-label', 'Статус');
            bar.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px';
            statuses.forEach(status => {
                const button = document.createElement('button');
                button.type = 'button';
                button.dataset.status = status;
                button.textContent = this.getLanguage().translateOption(status, 'status', 'Lead');
                button.onclick = () => this.changeStatus(status);
                bar.append(button);
            });
            host.prepend(bar);
            this.updateStatusButtons();
        }

        updateStatusButtons() {
            const bar = this.element && this.element.querySelector('.lead-status-actions');
            if (!bar) return;
            // Unsaved edits belong to the form; a one-click save here would mix with them.
            bar.style.display = this.mode === this.MODE_EDIT ? 'none' : 'flex';
            const current = this.model.get('status');
            bar.querySelectorAll('button').forEach(button => {
                const active = button.dataset.status === current;
                button.className = 'btn ' + (active ? 'btn-primary' : 'btn-default');
                button.setAttribute('aria-pressed', String(active));
                button.disabled = !!this.statusSaving;
            });
        }

        async changeStatus(status) {
            const previous = this.model.get('status');
            if (this.statusSaving || status === previous) return;
            this.statusSaving = true;
            this.updateStatusButtons();
            try {
                await this.model.save({status}, {patch: true});
                Espo.Ui.success(this.translate('Saved'));
            } catch (error) {
                // The CRM reports the reason itself; put the card back to the stored status.
                this.model.set('status', previous);
            } finally {
                this.statusSaving = false;
                this.updateStatusButtons();
            }
        }
    };
});
