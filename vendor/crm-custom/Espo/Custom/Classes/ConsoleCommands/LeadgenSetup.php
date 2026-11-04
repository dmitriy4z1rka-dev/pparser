<?php

namespace Espo\Custom\Classes\ConsoleCommands;

use Espo\Core\Console\Command;
use Espo\Core\Console\Command\Params;
use Espo\Core\Console\IO;
use Espo\Core\Field\LinkMultiple;
use Espo\Core\Utils\Config\ConfigWriter;
use Espo\Entities\Role;
use Espo\Entities\User;
use Espo\ORM\EntityManager;
use RuntimeException;

/** Idempotent setup of the lead workspace and a restricted integration API user. */
class LeadgenSetup implements Command
{
    public function __construct(private EntityManager $entityManager, private ConfigWriter $configWriter)
    {}

    public function run(Params $params, IO $io): void
    {
        $key = getenv('ESPO_API_KEY');
        if (!$key || strlen($key) < 32) {
            throw new RuntimeException('ESPO_API_KEY must contain at least 32 characters.');
        }
        $panelUrl = getenv('LEADGEN_PUBLIC_URL') ?: 'http://localhost:8090';
        $this->configWriter->setMultiple([
            'applicationName' => 'Лиды · EspoCRM',
            'language' => 'ru_RU',
            'tabList' => ['Lead', 'Task', (object) [
                'type' => 'url', 'text' => 'Сбор компаний', 'url' => $panelUrl,
                'iconClass' => 'fas fa-map-marked-alt', 'openInNewTab' => true,
            ]],
            'quickCreateList' => ['Lead', 'Task'],
            'globalSearchEntityList' => ['Lead'],
            'activitiesEntityList' => ['Task'],
            'historyEntityList' => ['Task'],
            'massEmailDisabled' => true,
        ]);
        $this->configWriter->save();

        $roles = $this->entityManager->getRDBRepositoryByClass(Role::class);
        $role = $roles->where(['name' => 'Leadgen API'])->findOne() ?? $roles->getNew();
        $role->set('name', 'Leadgen API');
        $role->setRawData([
            'Lead' => ['create' => 'yes', 'read' => 'all', 'edit' => 'all', 'delete' => 'no', 'stream' => 'no'],
            'Account' => false, 'Contact' => false, 'Opportunity' => false,
            'Campaign' => false, 'Case' => false, 'Task' => false,
        ]);
        $this->entityManager->saveEntity($role);

        $users = $this->entityManager->getRDBRepositoryByClass(User::class);
        $user = $users->where(['userName' => 'leadgen-integration'])->findOne();
        if ($user && !$user->isApi()) {
            throw new RuntimeException('The integration username is occupied by a non-API user.');
        }
        $user ??= $users->getNew();
        $user->set([
            'userName' => 'leadgen-integration', 'lastName' => 'Map collectors',
            'type' => 'api', 'isActive' => true, 'authMethod' => 'ApiKey', 'apiKey' => $key,
        ]);
        $user->setRoles(LinkMultiple::create()->withAddedIdList([$role->getId()]));
        $this->entityManager->saveEntity($user);
        $io->writeLine('Leadgen workspace configured. API key was not printed.');
    }
}
