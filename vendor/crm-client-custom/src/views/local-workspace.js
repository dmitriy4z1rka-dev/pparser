define('custom:views/local-workspace', ['view', 'ajax'], function (View, Ajax) {
    return class extends View {
        templateContent = '<main class="container content"><p class="text-muted" role="status">Открываем локальную базу…</p></main>';

        async afterRender() {
            try {
                const data = await Ajax.getRequest('App/user', {}, {login: true});
                this.trigger('login', data.user.userName, data);
            } catch (error) {
                this.el.querySelector('[role="status"]').textContent =
                    'Не удалось открыть базу. Проверьте запуск CRM и обновите страницу.';
            }
        }
    };
});
