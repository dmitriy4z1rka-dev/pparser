define('custom:views/lead-detail', ['views/record/detail'], function (DetailRecordView) {
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
    };
});
