import React, { memo, useMemo } from 'react';
import * as Ariakit from '@ariakit/react';
import { ChevronDown } from 'lucide-react';
import { PermissionTypes, Permissions } from 'librechat-data-provider';
import { TooltipAnchor, composerControlClasses } from '@librechat/client';
import MCPServerMenuItem from '~/components/MCP/MCPServerMenuItem';
import StackedMCPIcons from '~/components/MCP/StackedMCPIcons';
import { useMCPRefresh } from '~/hooks/MCP/useMCPRefresh';
import { useHasAccess, useLocalize } from '~/hooks';
import { useBadgeRowContext } from '~/Providers';
import { cn } from '~/utils';

function CompactMCPSelectContent() {
  const localize = useLocalize();
  const context = useBadgeRowContext();
  const manager = context?.mcpServerManager;
  const menuStore = Ariakit.useMenuStore({ focusLoop: true });
  const isOpen = menuStore.useState('open');

  useMCPRefresh({
    enabled: isOpen && (manager?.availableMCPServers.length ?? 0) > 0,
  });

  const selectedServers = useMemo(() => {
    if (!manager?.mcpValues?.length) {
      return [];
    }
    const selected = new Set(manager.mcpValues);
    return manager.selectableServers.filter((server) => selected.has(server.serverName));
  }, [manager?.mcpValues, manager?.selectableServers]);

  const displayText = useMemo(() => {
    if (selectedServers.length === 0) {
      return manager?.placeholderText;
    }
    if (selectedServers.length === 1) {
      return selectedServers[0].config?.title || selectedServers[0].serverName;
    }
    return `${selectedServers.length} selected`;
  }, [manager?.placeholderText, selectedServers]);

  if (!manager) {
    return null;
  }

  const {
    connectionStatus,
    getServerStatusIconProps,
    isInitializing,
    mcpValues,
    placeholderText,
    selectableServers,
    toggleServerSelection,
  } = manager;

  return (
    <Ariakit.MenuProvider store={menuStore}>
      <TooltipAnchor
        description={placeholderText}
        disabled={isOpen}
        render={
          <Ariakit.MenuButton
            className={cn(
              composerControlClasses(),
              'min-w-theme-control md:px-theme-normal px-2.5 md:w-fit md:justify-start',
              isOpen && 'bg-surface-hover',
            )}
          />
        }
      >
        <StackedMCPIcons selectedServers={selectedServers} maxIcons={3} iconSize="sm" />
        <span className="text-text-primary hidden truncate md:block">{displayText}</span>
        <ChevronDown
          className={cn(
            'text-text-secondary hidden h-3 w-3 transition-transform md:block',
            isOpen && 'rotate-180',
          )}
        />
      </TooltipAnchor>

      <Ariakit.Menu
        portal
        gutter={8}
        modal
        unmountOnHide
        aria-label={localize('com_ui_mcp_servers')}
        className={cn(
          'z-50 flex max-w-[320px] min-w-[260px] flex-col rounded-xl',
          'border-border-light bg-presentation border p-1.5 shadow-lg',
          'origin-top scale-95 opacity-0 transition-[opacity,transform] duration-200 ease-out',
          'data-[enter]:scale-100 data-[enter]:opacity-100',
          'data-[leave]:scale-95 data-[leave]:opacity-0',
        )}
      >
        <div className="flex max-h-[320px] flex-col gap-1 overflow-y-auto">
          {selectableServers.map((server) => (
            <MCPServerMenuItem
              key={server.serverName}
              server={server}
              isSelected={mcpValues?.includes(server.serverName) ?? false}
              connectionStatus={connectionStatus}
              isInitializing={isInitializing}
              statusIconProps={getServerStatusIconProps(server.serverName)}
              onToggle={toggleServerSelection}
            />
          ))}
        </div>
      </Ariakit.Menu>
    </Ariakit.MenuProvider>
  );
}

function CompactMCPSelect() {
  const context = useBadgeRowContext();
  const selectableServers = context?.mcpServerManager?.selectableServers;
  const canUseMcp = useHasAccess({
    permissionType: PermissionTypes.MCP_SERVERS,
    permission: Permissions.USE,
  });

  if (!canUseMcp || !selectableServers?.length) {
    return null;
  }

  return <CompactMCPSelectContent />;
}

export default memo(CompactMCPSelect);
