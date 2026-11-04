define('custom:views/local-navbar', ['views/site/navbar'], function (Navbar) {
    return class extends Navbar {
        setupMenu() {
            this.menuDataList = [];
        }

        getTabList() {
            return super.getTabList().filter(tab => tab !== 'Home');
        }

        afterRender() {
            super.afterRender();
            this.$el.find('.menu-container').remove();
        }
    };
});
